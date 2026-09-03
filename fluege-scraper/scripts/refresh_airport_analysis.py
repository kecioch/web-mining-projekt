#!/usr/bin/env python3
"""Startet die tägliche Flughafenanalyse in Supabase."""

import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from supabase_client import SupabaseClient


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Erforderliche Umgebungsvariable fehlt: {name}")
    return value


def is_true(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def analysis_date() -> date:
    """Liest das gewünschte Datum oder verwendet den gestrigen Tag als Service-Date."""
    configured = os.environ.get("ANALYSIS_DATE", "").strip()
    if configured:
        try:
            return date.fromisoformat(configured)
        except ValueError as exc:
            raise RuntimeError("ANALYSIS_DATE muss das Format YYYY-MM-DD haben") from exc
    return datetime.now(ZoneInfo("Europe/Berlin")).date() - timedelta(days=1)


def analyzed_airports(database: SupabaseClient, target_date: date) -> list[str]:
    """Formatiert die Flughäfen, für die Analysezeilen geschrieben wurden."""
    analysis_rows = database.fetch_all(
        "airport_analysis",
        "airport_icao",
        order="airport_icao",
        equal_filters={"analysis_date": target_date.isoformat()},
    )
    airport_codes = {
        str(row.get("airport_icao") or "").strip().upper()
        for row in analysis_rows
        if row.get("airport_icao")
    }
    if not airport_codes:
        return []

    airport_names = {
        str(row.get("icao") or "").strip().upper(): str(
            row.get("name") or ""
        ).strip()
        for row in database.fetch_all("airports", "icao,name", order="icao")
        if row.get("icao")
    }
    return [
        f"{airport_names[code]} ({code})" if airport_names.get(code) else code
        for code in sorted(airport_codes)
    ]


def main() -> None:
    target_date = analysis_date()
    try:
        threshold = int(os.environ.get("DELAY_THRESHOLD", "15"))
    except ValueError as exc:
        raise RuntimeError("DELAY_THRESHOLD muss eine ganze Zahl sein") from exc
    if threshold < 0:
        raise RuntimeError("DELAY_THRESHOLD darf nicht negativ sein")

    if is_true(os.environ.get("DRY_RUN")):
        print(
            f"Dry Run: Flughafenanalyse für {target_date.isoformat()} "
            f"mit Verspätungsgrenze > {threshold} Minuten würde gestartet."
        )
        print("Flughäfen werden beim tatsächlichen Lauf aus den Flugdaten ermittelt.")
        return

    database = SupabaseClient(
        required_env("SUPABASE_URL"),
        required_env("SUPABASE_SERVICE_KEY"),
    )
    row_count = database.call_rpc(
        "refresh_airport_analysis",
        {
            "p_analysis_date": target_date.isoformat(),
            "p_delay_threshold": threshold,
        },
    )
    airports = analyzed_airports(database, target_date)
    print(
        f"Flughafenanalyse für {target_date.isoformat()} abgeschlossen: "
        f"{row_count} Datensätze erstellt."
    )
    print(f"Flughäfen ({len(airports)}):")
    if airports:
        for airport in airports:
            print(f"  - {airport}")
    else:
        print("  - keine")


if __name__ == "__main__":
    main()
