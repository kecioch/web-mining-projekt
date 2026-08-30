#!/usr/bin/env python3
"""Importiert fertige Airport-Jobs aus Scrapy Cloud nach Supabase."""

import os
import sys

from flight_mapping_service import FlightMappingService
from iata_lookup_service import IataLookupService
from supabase_client import SupabaseClient, natural_key
from zyte_client import ZyteClient


SCRAPED_BY = "ZYTE_AIRPORT_FLIGHTS"
JOB_SEPARATOR = "=" * 72
RESULT_SEPARATOR = "#" * 72
SPIDER_NAMES = {
    "berlin_airport_flights": "Berlin",
    "frankfurt_airport_flights": "Frankfurt",
    "munich_airport_flights": "München",
}


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Erforderliche Umgebungsvariable fehlt: {name}")
    return value


def is_true(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def preview(values: set[str]) -> str:
    return ", ".join(sorted(values))


def print_job_header(job: dict, position: int, total: int, dry_run: bool) -> None:
    """Kennzeichnet vor der Verarbeitung eindeutig den folgenden Jobblock."""
    spider = job.get("spider", "unbekannter Spider")
    airport = SPIDER_NAMES.get(spider, spider)
    mode = "DRY RUN" if dry_run else "ECHTER IMPORT"
    print(f"\n{JOB_SEPARATOR}")
    print(f"JOB {position}/{total} | {airport} | {job.get('id', 'unbekannte ID')}")
    print(f"Modus: {mode}")
    print(JOB_SEPARATOR, flush=True)


def print_job_report(
    stats: dict,
    missing: dict[str, list[dict]],
    unmatched: dict[str, set[str]],
    new_examples: list[tuple[str, dict]],
    dry_run: bool,
) -> None:
    """Gibt Mengen, Stammdatenlücken und Beispiele eines Jobs gebündelt aus."""
    new_label = "Würden neu gespeichert" if dry_run else "Neu gespeichert"
    lookup_label = "Würden angelegt" if dry_run else "Neu angelegt"
    print("Flugdaten:")
    print(f"  Items gelesen:          {stats['items']}")
    print(f"  {new_label + ':':<24}{stats['new']}")
    print(f"  Bereits vorhanden:      {stats['existing']}")
    print(f"  Unvollständig:          {stats['incomplete']}")

    if new_examples:
        print("  Beispiele für neue Datensätze:")
        for table, row in new_examples:
            direction = "Ankunft" if table == "arrivals" else "Abflug"
            timestamp_field = (
                "scheduled_arrival_at"
                if table == "arrivals"
                else "scheduled_departure_at"
            )
            print(
                f"    - {direction} | {row['airport_icao']} | "
                f"{row['flight_no']} | {row[timestamp_field]}"
            )

    print("Stammdaten:")
    print(
        f"  {lookup_label}: "
        + " | ".join(f"{table}={len(rows)}" for table, rows in missing.items())
    )
    populated = [(label, values) for label, values in unmatched.items() if values]
    if not populated:
        print("  Nicht zugeordnet: keine")
        return
    print("  Nicht zugeordnet; entsprechender Fremdschlüssel bleibt NULL:")
    for label, values in populated:
        print(f"    - {label}: {len(values)} ({preview(values)})")


def print_summary(
    totals: dict[str, int], job_count: int, failure_count: int, dry_run: bool
) -> None:
    """Trennt das Gesamtergebnis sichtbar von allen Flughafenblöcken."""
    mode = "DRY RUN" if dry_run else "IMPORT ABGESCHLOSSEN"
    new_label = "Würden neu gespeichert" if dry_run else "Neu gespeichert"
    print(f"\n{RESULT_SEPARATOR}")
    print(f"GESAMTERGEBNIS | {mode}")
    print(RESULT_SEPARATOR)
    print(f"Jobs erfolgreich:         {job_count - failure_count}/{job_count}")
    print(f"Items gelesen:            {totals['items']}")
    print(f"{new_label + ':':<27}{totals['new']}")
    print(f"Bereits vorhanden:        {totals['existing']}")
    print(f"Unvollständig:            {totals['incomplete']}")




def import_job(
    job: dict,
    dry_run: bool,
    zyte: ZyteClient,
    database: SupabaseClient,
    mapper: FlightMappingService,
    iata_lookup: IataLookupService,
) -> dict[str, int]:
    """Verarbeitet einen Zyte-Job vollständig und markiert ihn erst nach Erfolg."""
    job_id = job.get("id")
    if not job_id:
        raise RuntimeError("Scrapy Cloud lieferte einen Job ohne ID")
    if job.get("close_reason") != "finished":
        raise RuntimeError(
            f"Job {job_id} ist nicht sauber beendet: {job.get('close_reason')}"
        )

    mapped = {"arrivals": [], "departures": []}
    collected = {"airports": {}, "airlines": {}, "aircraft": {}}
    unmatched = {"Airports": set(), "Airlines": set(), "Aircraft": set()}
    skipped = 0
    items = list(zyte.iter_items(job_id))
    item_count = len(items)

    if item_count == 0:
        raise RuntimeError(f"Job {job_id} enthält keine Items und bleibt db-pending")

    # Fehlende IATA-Codes vor dem eigentlichen Mapping automatisch auflösen.
    auto_collected = {"airports": {}, "airlines": {}, "aircraft": {}}
    mapper.collect_lookups(
        auto_collected,
        iata_lookup.resolve(mapper.unresolved_references(items)),
    )
    auto_missing = mapper.missing_lookups(auto_collected)
    if not dry_run:
        database.upsert_lookups(auto_missing)
    mapper.register_lookups(auto_missing)

    for item in items:
        result = mapper.map_item(item)
        if result is None:
            skipped += 1
            continue
        table, row, lookups = result
        row["scraped_by"] = SCRAPED_BY
        mapped[table].append(row)
        mapper.collect_lookups(collected, lookups)

        counterpart = "origin_icao" if table == "arrivals" else "destination_icao"
        if item.get("counterpart_iata_code") and not row.get(counterpart):
            unmatched["Airports"].add(str(item["counterpart_iata_code"]))
        if item.get("airline_iata_code") and not row.get("airline_icao"):
            unmatched["Airlines"].add(
                f"{item['airline_iata_code']} / {item.get('airline_name') or '?'}"
            )
        if item.get("aircraft_model") and not row.get("aircraft_code"):
            unmatched["Aircraft"].add(str(item["aircraft_model"]))

    remaining_missing = mapper.missing_lookups(collected)
    missing = {
        table: auto_missing[table] + remaining_missing[table]
        for table in collected
    }
    if not dry_run:
        database.upsert_lookups(remaining_missing)
    mapper.register_lookups(remaining_missing)

    inserted = 0
    duplicates = 0
    new_examples = []
    for table, rows in mapped.items():
        known_keys = database.existing_keys(table, rows)
        new_rows = []
        for row in rows:
            key = natural_key(table, row)
            if key in known_keys:
                duplicates += 1
            else:
                known_keys.add(key)
                new_rows.append(row)
                if len(new_examples) < 5:
                    new_examples.append((table, row))
        if not dry_run:
            database.insert_rows(table, new_rows)
        inserted += len(new_rows)

    stats = {
        "items": item_count,
        "new": inserted,
        "existing": duplicates,
        "incomplete": skipped,
    }
    print_job_report(stats, missing, unmatched, new_examples, dry_run)
    if not dry_run:
        zyte.mark_imported(job_id)
    return stats


def main() -> int:
    """Initialisiert alle Komponenten und importiert die wartenden Jobs nacheinander."""
    dry_run = is_true(os.environ.get("DRY_RUN"))
    database = SupabaseClient(
        required_env("SUPABASE_URL"), required_env("SUPABASE_SERVICE_KEY")
    )
    zyte = ZyteClient(
        required_env("SCRAPY_CLOUD_API_KEY"),
        required_env("SCRAPY_CLOUD_PROJECT_ID"),
    )
    jobs = zyte.list_pending_jobs()
    if not jobs:
        print("Keine fertigen Airport-Jobs mit db-pending gefunden.")
        return 0

    mapper = FlightMappingService(database.load_reference_rows())
    iata_lookup = IataLookupService()
    failures = []
    totals = {"items": 0, "new": 0, "existing": 0, "incomplete": 0}
    ordered_jobs = list(reversed(jobs))
    for position, job in enumerate(ordered_jobs, start=1):
        print_job_header(job, position, len(ordered_jobs), dry_run)
        try:
            stats = import_job(job, dry_run, zyte, database, mapper, iata_lookup)
            for key in totals:
                totals[key] += stats[key]
        except Exception as exc:  # Jobs unabhängig weiterverarbeiten
            job_id = job.get("id", "unbekannt")
            failures.append((job_id, str(exc)))
            print(f"FEHLER bei {job_id}: {exc}", file=sys.stderr)

    print_summary(totals, len(jobs), len(failures), dry_run)
    if failures:
        print("Fehlgeschlagene Jobs bleiben db-pending.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
