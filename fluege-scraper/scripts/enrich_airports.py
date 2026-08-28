#!/usr/bin/env python3
"""Ergänzt fehlende Flughafen-Stammdaten aus der OurAirports-CSV."""

import csv
import io
import os

import requests

from supabase_client import SupabaseClient


OURAIRPORTS_CSV_URL = (
    "https://davidmegginson.github.io/ourairports-data/airports.csv"
)
ENRICHMENT_FIELDS = ("iata", "latitude", "longitude", "website_url")


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Erforderliche Umgebungsvariable fehlt: {name}")
    return value


def is_true(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def is_empty(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def parse_float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def load_ourairports(wanted_icaos: set[str]) -> dict[str, dict]:
    """Lädt die OurAirports-CSV einmal und behält nur gesuchte ICAO-Codes."""
    response = requests.get(OURAIRPORTS_CSV_URL, timeout=90)
    response.raise_for_status()
    response.encoding = "utf-8"

    matches: dict[str, dict] = {}
    for row in csv.DictReader(io.StringIO(response.text)):
        # Bei Flughäfen mit offiziellem ICAO steht dieser normalerweise in ident;
        # gps_code dient als zusätzliche Absicherung.
        codes = {
            (row.get("ident") or "").strip().upper(),
            (row.get("gps_code") or "").strip().upper(),
        }
        code = next((candidate for candidate in codes if candidate in wanted_icaos), None)
        if not code:
            continue

        matches[code] = {
            "iata": (row.get("iata_code") or "").strip().upper() or None,
            "latitude": parse_float(row.get("latitude_deg")),
            "longitude": parse_float(row.get("longitude_deg")),
            "website_url": (row.get("home_link") or "").strip() or None,
        }

    return matches


def missing_values(airport: dict, source: dict) -> dict:
    return {
        field: source[field]
        for field in ENRICHMENT_FIELDS
        if is_empty(airport.get(field)) and source.get(field) is not None
    }


def main() -> None:
    """Ergänzt ausschließlich fehlende Werte bereits vorhandener Flughäfen."""
    dry_run = is_true(os.environ.get("DRY_RUN", "true"))
    database = SupabaseClient(
        required_env("SUPABASE_URL"), required_env("SUPABASE_SERVICE_KEY")
    )
    airports = database.fetch_all(
        "airports", "icao,iata,latitude,longitude,website_url", order="icao"
    )
    incomplete = [
        airport
        for airport in airports
        if any(is_empty(airport.get(field)) for field in ENRICHMENT_FIELDS)
    ]
    wanted_icaos = {
        str(airport.get("icao") or "").strip().upper()
        for airport in incomplete
        if airport.get("icao")
    }
    reference = load_ourairports(wanted_icaos)

    updated = 0
    unchanged = 0
    not_found: list[str] = []

    for airport in incomplete:
        icao = str(airport.get("icao") or "").strip().upper()
        source = reference.get(icao)
        if not source:
            not_found.append(icao)
            continue

        values = missing_values(airport, source)
        if not values:
            unchanged += 1
            continue

        print(f"{icao}: ergänze {', '.join(values)}")
        if not dry_run:
            database.patch_equal("airports", "icao", icao, values)
        updated += 1

    mode = "TESTLAUF - keine DB-Änderung" if dry_run else "DB aktualisiert"
    print(f"\nModus: {mode}")
    print(f"Geprüft: {len(airports)}")
    print(f"Unvollständig: {len(incomplete)}")
    print(f"Ergänzbar: {updated}")
    print(f"Ohne neue Werte: {unchanged}")
    print(f"Nicht gefunden: {len(not_found)}")
    if not_found:
        print("ICAO nicht gefunden: " + ", ".join(sorted(not_found)))


if __name__ == "__main__":
    main()
