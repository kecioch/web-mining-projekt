"""Wiederverwendbarer REST-Client für Supabase."""

from datetime import datetime, timezone

import requests


PAGE_SIZE = 1000
BATCH_SIZE = 500
LOOKUP_KEYS = {"airports": "icao", "airlines": "icao", "aircraft": "code"}


def canonical_timestamp(value: str) -> str:
    return (
        datetime.fromisoformat(value)
        .astimezone(timezone.utc)
        .isoformat(timespec="seconds")
    )


def natural_key(table: str, row: dict) -> tuple[str, str, str]:
    timestamp_column = (
        "scheduled_arrival_at" if table == "arrivals" else "scheduled_departure_at"
    )
    return (
        row["airport_icao"],
        row["flight_no"],
        canonical_timestamp(row[timestamp_column]),
    )


class SupabaseClient:
    """
    Die Klasse kapselt alle HTTP-Zugriffe auf die Supabase-REST-API.
    """

    def __init__(self, url: str, service_key: str):
        self.base_url = f"{url.rstrip('/')}/rest/v1"
        self.headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }

    def _endpoint(self, table: str) -> str:
        return f"{self.base_url}/{table}"

    @staticmethod
    def _json(response: requests.Response):
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"HTTP {response.status_code} für {response.url}: "
                f"{response.text[:2000]}"
            ) from exc
        return response.json()

    def fetch_all(
        self,
        table: str,
        columns: str,
        order: str | None = None,
        equal_filters: dict[str, str] | None = None,
    ) -> list[dict]:
        """Lädt eine vollständige Tabelle seitenweise über die Supabase-REST-API."""
        rows = []
        offset = 0
        while True:
            params = {
                "select": columns,
                "limit": PAGE_SIZE,
                "offset": offset,
            }
            if order:
                params["order"] = order
            if equal_filters:
                params.update(
                    {column: f"eq.{value}" for column, value in equal_filters.items()}
                )
            response = requests.get(
                self._endpoint(table),
                params=params,
                headers=self.headers,
                timeout=60,
            )
            page = self._json(response)
            if not isinstance(page, list):
                raise RuntimeError(f"Supabase-Tabelle {table} lieferte keine Liste")
            rows.extend(page)
            if len(page) < PAGE_SIZE:
                return rows
            offset += PAGE_SIZE

    def load_reference_rows(self) -> dict[str, list[dict]]:
        """Lädt die drei Stammdatentabellen für das Mapping der Flugbewegungen."""
        return {
            "airports": self.fetch_all("airports", "icao,iata,name"),
            "airlines": self.fetch_all("airlines", "icao,iata,name,legal_name"),
            "aircraft": self.fetch_all("aircraft", "code"),
        }

    def existing_keys(self, table: str, rows: list[dict]) -> set[tuple[str, str, str]]:
        """Ermittelt bereits gespeicherte Flüge im relevanten Zeitfenster."""
        if not rows:
            return set()
        timestamp_column = (
            "scheduled_arrival_at"
            if table == "arrivals"
            else "scheduled_departure_at"
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
        while True:
            response = requests.get(
                self._endpoint(table),
                params=base_params + [("limit", PAGE_SIZE), ("offset", offset)],
                headers=self.headers,
                timeout=60,
            )
            page = self._json(response)
            if not isinstance(page, list):
                raise RuntimeError(f"Supabase-Tabelle {table} lieferte keine Liste")
            existing.extend(page)
            if len(page) < PAGE_SIZE:
                break
            offset += PAGE_SIZE

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

    def upsert_lookups(self, rows_by_table: dict[str, list[dict]]) -> None:
        """Legt fehlende Stammdaten gebündelt an, ohne bestehende Zeilen zu ändern."""
        for table, rows in rows_by_table.items():
            key = LOOKUP_KEYS[table]
            self._write_batches(
                "post",
                table,
                rows,
                params={"on_conflict": key},
                prefer="resolution=ignore-duplicates,return=minimal",
            )

    def insert_rows(self, table: str, rows: list[dict]) -> None:
        """Schreibt neue Flugbewegungen in begrenzten Paketen nach Supabase."""
        self._write_batches("post", table, rows, prefer="return=minimal")

    def patch_equal(
        self, table: str, key_field: str, key_value: str, values: dict
    ) -> None:
        """Ergänzt ausgewählte Spalten einer vorhandenen Zeile über ihren Schlüssel."""
        response = requests.patch(
            self._endpoint(table),
            params={key_field: f"eq.{key_value}"},
            headers={**self.headers, "Prefer": "return=minimal"},
            json=values,
            timeout=30,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Supabase-Aktualisierung von {table} fehlgeschlagen "
                f"({response.status_code}): {response.text[:2000]}"
            ) from exc

    def call_rpc(self, function_name: str, parameters: dict):
        """Ruft eine freigegebene Postgres-Funktion über die Supabase-API auf."""
        response = requests.post(
            f"{self.base_url}/rpc/{function_name}",
            headers=self.headers,
            json=parameters,
            timeout=120,
        )
        return self._json(response)

    def _write_batches(
        self,
        method: str,
        table: str,
        rows: list[dict],
        params: dict | None = None,
        prefer: str | None = None,
    ) -> None:
        """Teilt größere Schreibvorgänge in API-verträgliche Pakete auf."""
        if not rows:
            return
        headers = dict(self.headers)
        if prefer:
            headers["Prefer"] = prefer
        for start in range(0, len(rows), BATCH_SIZE):
            response = requests.request(
                method,
                self._endpoint(table),
                params=params,
                headers=headers,
                json=rows[start : start + BATCH_SIZE],
                timeout=60,
            )
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                raise RuntimeError(
                    f"Supabase-Schreibzugriff auf {table} fehlgeschlagen "
                    f"({response.status_code}): {response.text[:2000]}"
                ) from exc
