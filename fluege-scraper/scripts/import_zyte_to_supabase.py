#!/usr/bin/env python3
"""Importiert fertige Airport-Jobs aus Scrapy Cloud nach Supabase."""

import os
import sys

from flight_mapping_service import FlightMappingService
from supabase_client import SupabaseClient, natural_key
from zyte_client import ZyteClient


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Erforderliche Umgebungsvariable fehlt: {name}")
    return value


def is_true(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def import_job(
    job: dict,
    dry_run: bool,
    zyte: ZyteClient,
    database: SupabaseClient,
    mapper: FlightMappingService,
) -> int:
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
    item_count = 0

    for item in zyte.iter_items(job_id):
        item_count += 1
        result = mapper.map_item(item)
        if result is None:
            skipped += 1
            continue
        table, row, lookups = result
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

    if item_count == 0:
        raise RuntimeError(f"Job {job_id} enthält keine Items und bleibt db-pending")

    missing = mapper.missing_lookups(collected)
    print("Neue Lookups: " + ", ".join(f"{k}={len(v)}" for k, v in missing.items()))
    if not dry_run:
        database.upsert_lookups(missing)
    mapper.register_lookups(missing)

    for label, values in unmatched.items():
        if values:
            print(
                f"Nicht gemappte {label}: {len(values)} "
                f"({', '.join(sorted(values)[:10])})"
            )

    inserted = 0
    duplicates = 0
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
        if not dry_run:
            database.insert_rows(table, new_rows)
        inserted += len(new_rows)

    print(
        f"{job_id} ({job['spider']}): {item_count} Items, "
        f"{inserted} neu, {duplicates} vorhanden, {skipped} unvollständig"
    )
    if not dry_run:
        zyte.mark_imported(job_id)
    return inserted


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
    failures = []
    total_inserted = 0
    for job in reversed(jobs):
        try:
            total_inserted += import_job(job, dry_run, zyte, database, mapper)
        except Exception as exc:  # Jobs unabhängig weiterverarbeiten
            job_id = job.get("id", "unbekannt")
            failures.append((job_id, str(exc)))
            print(f"FEHLER bei {job_id}: {exc}", file=sys.stderr)

    print(
        f"Ergebnis: {len(jobs) - len(failures)}/{len(jobs)} Jobs, "
        f"{total_inserted} neue Datensätze."
    )
    if failures:
        print("Fehlgeschlagene Jobs bleiben db-pending.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
