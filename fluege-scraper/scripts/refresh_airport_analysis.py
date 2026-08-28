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
    print(
        f"Flughafenanalyse für {target_date.isoformat()} abgeschlossen: "
        f"{row_count} Datensätze erstellt."
    )


if __name__ == "__main__":
    main()