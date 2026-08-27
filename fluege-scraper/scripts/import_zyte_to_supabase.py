#!/usr/bin/env python3
"""Importiert fertige Airport-Jobs aus Scrapy Cloud nach Supabase."""

import os
import sys
from collections.abc import Iterator
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests


JOBS_URL = "https://app.zyte.com/api/jobs/list.json"
JOBS_UPDATE_URL = "https://app.zyte.com/api/jobs/update.json"
ITEMS_URL = "https://storage.zyte.com/items/{job_id}"
SOURCE_TAG = "airport-daily"
PENDING_TAG = "db-pending"
IMPORTED_TAG = "db-imported"
AIRPORT_SPIDERS = {
    "berlin_airport_flights",
    "frankfurt_airport_flights",
    "munich_airport_flights",
}
ITEM_PAGE_SIZE = 1000
SUPABASE_BATCH_SIZE = 500


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Erforderliche Umgebungsvariable fehlt: {name}")
    return value


def is_true(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def scrapy_auth() -> tuple[str, str]:
    return required_env("SCRAPY_CLOUD_API_KEY"), ""


def supabase_headers(prefer: str | None = None) -> dict[str, str]:
    key = required_env("SUPABASE_SERVICE_KEY")
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def supabase_endpoint(table: str) -> str:
    return f"{required_env('SUPABASE_URL').rstrip('/')}/rest/v1/{table}"


def response_json(response: requests.Response):
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        body = response.text[:2000]
        raise RuntimeError(
            f"HTTP {response.status_code} fuer {response.url}: {body}"
        ) from exc
    return response.json()


def list_pending_jobs(project_id: str) -> list[dict]:
    response = requests.get(
        JOBS_URL,
        params={
            "project": project_id,
            "state": "finished",
            "has_tag": SOURCE_TAG,
            "lacks_tag": IMPORTED_TAG,
            "count": 100,
        },
        auth=scrapy_auth(),
        timeout=30,
    )
    payload = response_json(response)
    jobs = payload.get("jobs", [])
    if not isinstance(jobs, list):
        raise RuntimeError("Scrapy Cloud lieferte keine gueltige Jobliste")
    selected = []
    for job in jobs:
        tags = set(job.get("tags") or [])
        if job.get("spider") not in AIRPORT_SPIDERS:
            continue
        if SOURCE_TAG not in tags or PENDING_TAG not in tags:
            continue
        selected.append(job)
    return selected


def iter_job_items(job_id: str) -> Iterator[dict]:
    last_item_key = None
    while True:
        params: list[tuple[str, str | int]] = [
            ("count", ITEM_PAGE_SIZE),
            ("meta", "_key"),
        ]
        if last_item_key:
            params.append(("startafter", last_item_key))
        response = requests.get(
            ITEMS_URL.format(job_id=job_id),
            params=params,
            headers={"Accept": "application/json"},
            auth=scrapy_auth(),
            timeout=60,
        )
        items = response_json(response)
        if not isinstance(items, list):
            raise RuntimeError(f"Job {job_id} lieferte kein JSON-Array")
        if not items:
            return
        for item in items:
            if not isinstance(item, dict):
                raise RuntimeError(f"Job {job_id} enthaelt ein ungueltiges Item")
            yield item
            last_item_key = item.get("_key", last_item_key)
        if len(items) < ITEM_PAGE_SIZE:
            return
        if not last_item_key:
            raise RuntimeError(f"Job {job_id}: Pagination ohne Item-_key unmoeglich")


def fetch_all(table: str, columns: str) -> list[dict]:
    rows = []
    offset = 0
    page_size = 1000
    while True:
        response = requests.get(
            supabase_endpoint(table),
            params={"select": columns, "limit": page_size, "offset": offset},
            headers=supabase_headers(),
            timeout=60,
        )
        page = response_json(response)
        if not isinstance(page, list):
            raise RuntimeError(f"Supabase-Tabelle {table} lieferte keine Liste")
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size


def normalize_name(value) -> str | None:
    if not value:
        return None
    return " ".join(str(value).casefold().split())


def load_reference_data() -> dict:
    airports = {
        row["icao"] for row in fetch_all("airports", "icao") if row.get("icao")
    }
    aircraft = {
        row["code"] for row in fetch_all("aircraft", "code") if row.get("code")
    }
    airline_by_name = {}
    ambiguous_names = set()
    for row in fetch_all("airlines", "icao,name"):
        name = normalize_name(row.get("name"))
        icao = row.get("icao")
        if not name or not icao:
            continue
        if name in airline_by_name and airline_by_name[name] != icao:
            ambiguous_names.add(name)
        else:
            airline_by_name[name] = icao
    for name in ambiguous_names:
        airline_by_name.pop(name, None)
    return {
        "airports": airports,
        "aircraft": aircraft,
        "airline_by_name": airline_by_name,
    }


def timezone_for(item: dict):
    name = item.get("local_timezone") or "Europe/Berlin"
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Europe/Berlin")


def parse_timestamp(value, item: dict) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed_time = time.fromisoformat(text)
            service_date = date.fromisoformat(str(item.get("service_date")))
            parsed = datetime.combine(service_date, parsed_time)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone_for(item))
    return parsed


def iso_timestamp(value, item: dict) -> str | None:
    parsed = parse_timestamp(value, item)
    return parsed.isoformat(timespec="seconds") if parsed else None


def clock_time(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).time().isoformat(timespec="seconds")
    except ValueError:
        return None


def canonical_timestamp(value: str) -> str:
    return (
        datetime.fromisoformat(value)
        .astimezone(timezone.utc)
        .isoformat(timespec="seconds")
    )


def nullable_fk(value, valid_values: set[str]) -> str | None:
    return str(value) if value and str(value) in valid_values else None


def map_item(item: dict, references: dict) -> tuple[str, dict] | None:
    movement = str(item.get("movement_type") or "").lower()
    if movement not in {"arrival", "departure"}:
        return None
    scheduled_departure = iso_timestamp(item.get("scheduled_departure_local"), item)
    reported_departure = iso_timestamp(item.get("actual_departure_local"), item)
    scheduled_arrival = iso_timestamp(item.get("scheduled_arrival_local"), item)
    reported_arrival = iso_timestamp(item.get("actual_arrival_local"), item)
    if movement == "arrival":
        scheduled_arrival = scheduled_arrival or iso_timestamp(
            item.get("scheduled_time_local"), item
        )
        reported_arrival = reported_arrival or iso_timestamp(
            item.get("reported_time_local"), item
        )
    else:
        scheduled_departure = scheduled_departure or iso_timestamp(
            item.get("scheduled_time_local"), item
        )
        reported_departure = reported_departure or iso_timestamp(
            item.get("reported_time_local"), item
        )

    airport_icao = nullable_fk(item.get("airport_icao_code"), references["airports"])
    flight_number = item.get("flight_number")
    key_timestamp = scheduled_arrival if movement == "arrival" else scheduled_departure
    if not airport_icao or not flight_number or not key_timestamp:
        return None

    observed_at = iso_timestamp(item.get("observed_at_utc"), item)
    airline_icao = references["airline_by_name"].get(
        normalize_name(item.get("airline_name"))
    )
    aircraft_code = nullable_fk(item.get("aircraft_model"), references["aircraft"])
    local_timezone = item.get("local_timezone") or "Europe/Berlin"
    row = {
        "scraped_at": observed_at or datetime.now(timezone.utc).isoformat(),
        "airport_icao": airport_icao,
        "flight_no": str(flight_number),
        "airline_icao": airline_icao,
        "aircraft_code": aircraft_code,
        "departure_time": clock_time(scheduled_departure),
        "departure_time_tz": local_timezone if scheduled_departure else None,
        "arrival_time": clock_time(scheduled_arrival),
        "arrival_time_tz": local_timezone if scheduled_arrival else None,
        "delay_minutes": (
            item.get("arrival_delay_minutes")
            if movement == "arrival"
            else item.get("departure_delay_minutes")
        ),
        "scheduled_departure_at": scheduled_departure,
        "reported_departure_at": reported_departure,
        "scheduled_arrival_at": scheduled_arrival,
        "reported_arrival_at": reported_arrival,
    }
    if movement == "arrival":
        row.update(
            {
                "origin_icao": nullable_fk(
                    item.get("origin_icao_code"), references["airports"]
                ),
                "arrival_status": item.get("status_raw"),
            }
        )
        return "arrivals", row
    row.update(
        {
            "destination_icao": nullable_fk(
                item.get("destination_icao_code"), references["airports"]
            ),
            "departure_status": item.get("status_raw"),
        }
    )
    return "departures", row


def natural_key(table: str, row: dict) -> tuple[str, str, str]:
    timestamp_column = (
        "scheduled_arrival_at" if table == "arrivals" else "scheduled_departure_at"
    )
    return (
        row["airport_icao"],
        row["flight_no"],
        canonical_timestamp(row[timestamp_column]),
    )


def existing_keys(table: str, rows: list[dict]) -> set[tuple[str, str, str]]:
    if not rows:
        return set()
    timestamp_column = (
        "scheduled_arrival_at" if table == "arrivals" else "scheduled_departure_at"
    )
    timestamps = [
        datetime.fromisoformat(row[timestamp_column]).astimezone(timezone.utc)
        for row in rows
    ]
    base_params: list[tuple[str, str | int]] = [
        ("select", f"airport_icao,flight_no,{timestamp_column}"),
        (timestamp_column, f"gte.{min(timestamps).isoformat()}"),
        (timestamp_column, f"lte.{max(timestamps).isoformat()}"),
    ]
    existing = []
    offset = 0
    page_size = 1000
    while True:
        response = requests.get(
            supabase_endpoint(table),
            params=base_params + [("limit", page_size), ("offset", offset)],
            headers=supabase_headers(),
            timeout=60,
        )
        page = response_json(response)
        if not isinstance(page, list):
            raise RuntimeError(f"Supabase-Tabelle {table} lieferte keine Liste")
        existing.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    keys = set()
    for row in existing:
        value = row.get(timestamp_column)
        if row.get("airport_icao") and row.get("flight_no") and value:
            keys.add(
                (
                    row["airport_icao"],
                    row["flight_no"],
                    canonical_timestamp(value),
                )
            )
    return keys


def insert_rows(table: str, rows: list[dict]) -> None:
    for start in range(0, len(rows), SUPABASE_BATCH_SIZE):
        batch = rows[start : start + SUPABASE_BATCH_SIZE]
        response = requests.post(
            supabase_endpoint(table),
            headers=supabase_headers("return=minimal"),
            json=batch,
            timeout=60,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Supabase-Insert in {table} fehlgeschlagen "
                f"({response.status_code}): {response.text[:2000]}"
            ) from exc


def update_job_tags(project_id: str, job_id: str) -> None:
    response = requests.post(
        JOBS_UPDATE_URL,
        data={
            "project": project_id,
            "job": job_id,
            "add_tag": IMPORTED_TAG,
            "remove_tag": PENDING_TAG,
        },
        auth=scrapy_auth(),
        timeout=30,
    )
    payload = response_json(response)
    if payload.get("status") != "ok":
        raise RuntimeError(f"Tags fuer Job {job_id} nicht aktualisiert: {payload}")


def import_job(project_id: str, job: dict, references: dict, dry_run: bool) -> int:
    job_id = job.get("id")
    if not job_id:
        raise RuntimeError("Scrapy Cloud lieferte einen Job ohne ID")
    if job.get("close_reason") != "finished":
        raise RuntimeError(
            f"Job {job_id} ist nicht sauber beendet: {job.get('close_reason')}"
        )
    mapped = {"arrivals": [], "departures": []}
    skipped = 0
    item_count = 0
    for item in iter_job_items(job_id):
        item_count += 1
        result = map_item(item, references)
        if result is None:
            skipped += 1
            continue
        table, row = result
        mapped[table].append(row)
    if item_count == 0:
        raise RuntimeError(f"Job {job_id} enthaelt keine Items und bleibt db-pending")

    inserted = 0
    duplicates = 0
    for table, rows in mapped.items():
        known_keys = existing_keys(table, rows)
        new_rows = []
        for row in rows:
            key = natural_key(table, row)
            if key in known_keys:
                duplicates += 1
                continue
            known_keys.add(key)
            new_rows.append(row)
        if not dry_run:
            insert_rows(table, new_rows)
        inserted += len(new_rows)
    print(
        f"{job_id} ({job['spider']}): {item_count} Items, "
        f"{inserted} neu, {duplicates} vorhanden, {skipped} unvollstaendig"
    )
    if not dry_run:
        update_job_tags(project_id, job_id)
    return inserted


def main() -> int:
    project_id = required_env("SCRAPY_CLOUD_PROJECT_ID")
    dry_run = is_true(os.environ.get("DRY_RUN"))
    jobs = list_pending_jobs(project_id)
    if not jobs:
        print("Keine fertigen Airport-Jobs mit db-pending gefunden.")
        return 0
    references = load_reference_data()
    failures = []
    total_inserted = 0
    for job in reversed(jobs):
        try:
            total_inserted += import_job(project_id, job, references, dry_run)
        except Exception as exc:  # Jobs unabhaengig weiterverarbeiten
            job_id = job.get("id", "unbekannt")
            failures.append((job_id, str(exc)))
            print(f"FEHLER bei {job_id}: {exc}", file=sys.stderr)
    print(
        f"Ergebnis: {len(jobs) - len(failures)}/{len(jobs)} Jobs, "
        f"{total_inserted} neue Datensaetze."
    )
    if failures:
        print("Fehlgeschlagene Jobs bleiben db-pending.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
