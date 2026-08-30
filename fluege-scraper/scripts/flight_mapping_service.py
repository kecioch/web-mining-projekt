"""Überführt gescrapte Airport-Items in das Supabase-Datenmodell."""

import re
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


AIRCRAFT_CODE_RE = re.compile(r"^[A-Z0-9]{2,4}$")
LOOKUP_SPECS = {
    "airports": ("icao", "airports"),
    "airlines": ("icao", "airlines"),
    "aircraft": ("code", "aircraft"),
}


def normalize_name(value) -> str | None:
    if not value:
        return None
    return " ".join(str(value).casefold().split())


def normalize_code(value) -> str | None:
    if not value:
        return None
    code = str(value).strip().upper()
    return None if not code or code in {"NULL", "NONE", "N/A"} else code


def add_unique_name_mapping(
    mapping: dict[str, str], ambiguous: set[str], name, icao
) -> None:
    name = normalize_name(name)
    icao = normalize_code(icao)
    if not name or not icao or name in ambiguous:
        return
    previous = mapping.get(name)
    if previous and previous != icao:
        mapping.pop(name, None)
        ambiguous.add(name)
    else:
        mapping[name] = icao


class FlightMappingService:
    """
    Die Klasse kapselt Stammdatenauflösung und Transformation der gescrapten Items.
    """

    def __init__(self, reference_rows: dict[str, list[dict]]):
        self.reference_rows = {
            table: list(rows) for table, rows in reference_rows.items()
        }
        self.references = self._build_references(self.reference_rows)

    @staticmethod
    def _build_references(rows: dict[str, list[dict]]) -> dict:
        """Baut aus Supabase-Zeilen eindeutige IATA-, ICAO- und Namensindizes."""
        airports = rows["airports"]
        airport_candidates: dict[str, set[str]] = {}
        airport_names = {}
        for row in airports:
            icao = normalize_code(row.get("icao"))
            iata = normalize_code(row.get("iata"))
            if not icao:
                continue
            if iata:
                airport_candidates.setdefault(iata, set()).add(icao)
            if row.get("name"):
                airport_names[icao] = row["name"]

        airport_by_iata = {}
        ambiguous_airports = {}
        for iata, icaos in airport_candidates.items():
            if len(icaos) == 1:
                icao = next(iter(icaos))
                airport_by_iata[iata] = {
                    "icao": icao,
                    "name": airport_names.get(icao),
                }
            else:
                ambiguous_airports[iata] = sorted(icaos)
        if ambiguous_airports:
            print(
                "Mehrdeutige Airport-IATA-Codes werden ignoriert: "
                f"{ambiguous_airports}"
            )

        airlines = rows["airlines"]
        airline_candidates: dict[str, set[str]] = {}
        airline_names = {}
        airline_by_name = {}
        ambiguous_names: set[str] = set()
        airline_icaos = set()
        for row in airlines:
            icao = normalize_code(row.get("icao"))
            iata = normalize_code(row.get("iata"))
            if not icao:
                continue
            airline_icaos.add(icao)
            if iata:
                airline_candidates.setdefault(iata, set()).add(icao)
            if row.get("name"):
                airline_names[icao] = row["name"]
            add_unique_name_mapping(
                airline_by_name, ambiguous_names, row.get("name"), icao
            )
            add_unique_name_mapping(
                airline_by_name, ambiguous_names, row.get("legal_name"), icao
            )

        return {
            "airports": {
                code for row in airports if (code := normalize_code(row.get("icao")))
            },
            "airlines": airline_icaos,
            "aircraft": {
                code
                for row in rows["aircraft"]
                if (code := normalize_code(row.get("code")))
            },
            "airport_by_iata": airport_by_iata,
            "airport_name_by_icao": airport_names,
            "airline_iata_candidates": airline_candidates,
            "airline_name_by_icao": airline_names,
            "airline_by_name": airline_by_name,
        }

    @staticmethod
    def _timezone(item: dict):
        try:
            return ZoneInfo(item.get("local_timezone") or "Europe/Berlin")
        except ZoneInfoNotFoundError:
            return ZoneInfo("Europe/Berlin")

    def _timestamp(self, value, item: dict) -> str | None:
        """Normalisiert vollständige oder lokale Zeitangaben zu ISO-Zeitstempeln."""
        if not value:
            return None
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.combine(
                    date.fromisoformat(str(item.get("service_date"))),
                    time.fromisoformat(text),
                )
            except (TypeError, ValueError):
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=self._timezone(item))
        return parsed.isoformat(timespec="seconds")

    @staticmethod
    def _clock(value: str | None) -> str | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value).time().isoformat(timespec="seconds")
        except ValueError:
            return None

    def _field_timestamp(
        self, item: dict, current_field: str, legacy_field: str
    ) -> str | None:
        return self._timestamp(
            item.get(current_field) or item.get(legacy_field), item
        )

    def _resolve_airport(self, item: dict) -> tuple[str | None, str | None]:
        direct = normalize_code(item.get("counterpart_icao_code"))
        if direct:
            return direct, self.references["airport_name_by_icao"].get(direct)
        iata = normalize_code(item.get("counterpart_iata_code"))
        mapped = self.references["airport_by_iata"].get(iata) if iata else None
        return (mapped["icao"], mapped.get("name")) if mapped else (None, None)

    def _resolve_airline(self, item: dict) -> tuple[str | None, str | None]:
        """Ordnet Airline-IATA oder -Name ausschließlich vorhandenen ICAOs zu."""
        raw_code = normalize_code(item.get("airline_iata_code"))
        source_name = item.get("airline_name") or None
        name_match = self.references["airline_by_name"].get(
            normalize_name(source_name)
        )
        if raw_code in self.references["airlines"]:
            icao = raw_code
        else:
            candidates = self.references["airline_iata_candidates"].get(
                raw_code, set()
            )
            if name_match in candidates:
                icao = name_match
            elif len(candidates) == 1:
                icao = next(iter(candidates))
            else:
                icao = name_match
        if not icao:
            return None, None
        return icao, self.references["airline_name_by_icao"].get(icao) or source_name

    def _resolve_aircraft(self, item: dict) -> str | None:
        model = normalize_code(item.get("aircraft_model"))
        if model and (
            model in self.references["aircraft"] or AIRCRAFT_CODE_RE.fullmatch(model)
        ):
            return model
        return None

    def unresolved_references(self, items: list[dict]) -> dict:
        """Sammelt nur IATA- und Namenswerte, die lokal noch nicht auflösbar sind."""
        airports: dict[str, set[str]] = {}
        airlines: dict[tuple[str | None, str | None], dict] = {}
        for item in items:
            airport_iata = normalize_code(item.get("counterpart_iata_code"))
            if (
                airport_iata
                and not normalize_code(item.get("counterpart_icao_code"))
                and not self._resolve_airport(item)[0]
            ):
                airports.setdefault(airport_iata, set()).add(
                    str(item.get("counterpart_airport_name") or "")
                )

            airline_code = normalize_code(item.get("airline_iata_code"))
            airline_name = item.get("airline_name") or None
            if (airline_code or airline_name) and not self._resolve_airline(item)[0]:
                key = (airline_code, normalize_name(airline_name))
                airlines[key] = {"code": airline_code, "name": airline_name}

        return {"airports": airports, "airlines": list(airlines.values())}

    def map_item(self, item: dict) -> tuple[str, dict, dict] | None:
        """Erzeugt Flugzeile und benötigte Stammdaten aus einem Zyte-Item."""
        movement = str(item.get("movement_type") or "").lower()
        if movement not in {"arrival", "departure"}:
            return None

        scheduled_departure = self._field_timestamp(
            item, "scheduled_departure_at", "scheduled_departure_local"
        )
        reported_departure = self._field_timestamp(
            item, "reported_departure_at", "actual_departure_local"
        )
        scheduled_arrival = self._field_timestamp(
            item, "scheduled_arrival_at", "scheduled_arrival_local"
        )
        reported_arrival = self._field_timestamp(
            item, "reported_arrival_at", "actual_arrival_local"
        )
        if movement == "arrival":
            scheduled_arrival = scheduled_arrival or self._timestamp(
                item.get("scheduled_time_local"), item
            )
            reported_arrival = reported_arrival or self._timestamp(
                item.get("reported_time_local"), item
            )
        else:
            scheduled_departure = scheduled_departure or self._timestamp(
                item.get("scheduled_time_local"), item
            )
            reported_departure = reported_departure or self._timestamp(
                item.get("reported_time_local"), item
            )

        airport_icao = normalize_code(item.get("airport_icao_code"))
        flight_number = item.get("flight_number")
        key_time = scheduled_arrival if movement == "arrival" else scheduled_departure
        if not airport_icao or not flight_number or not key_time:
            return None

        counterpart_icao, counterpart_name = self._resolve_airport(item)
        airline_icao, airline_name = self._resolve_airline(item)
        aircraft_code = self._resolve_aircraft(item)
        timezone_name = item.get("local_timezone") or "Europe/Berlin"
        lookups = {
            "airports": [
                {"icao": airport_icao, "name": item.get("airport_name") or None}
            ],
            "airlines": [],
            "aircraft": [],
        }
        if counterpart_icao:
            lookups["airports"].append(
                {
                    "icao": counterpart_icao,
                    "name": counterpart_name
                    or item.get("counterpart_airport_name")
                    or None,
                }
            )
        if airline_icao:
            lookups["airlines"].append({"icao": airline_icao, "name": airline_name})
        if aircraft_code:
            lookups["aircraft"].append({"code": aircraft_code})

        row = {
            "scraped_at": self._timestamp(item.get("observed_at_utc"), item)
            or datetime.now(timezone.utc).isoformat(),
            "airport_icao": airport_icao,
            "flight_no": str(flight_number),
            "airline_icao": airline_icao,
            "aircraft_code": aircraft_code,
            "departure_time": self._clock(scheduled_departure),
            "departure_time_tz": timezone_name if scheduled_departure else None,
            "arrival_time": self._clock(scheduled_arrival),
            "arrival_time_tz": timezone_name if scheduled_arrival else None,
            "delay_minutes": item.get(
                "arrival_delay_minutes"
                if movement == "arrival"
                else "departure_delay_minutes"
            ),
            "scheduled_departure_at": scheduled_departure,
            "reported_departure_at": reported_departure,
            "scheduled_arrival_at": scheduled_arrival,
            "reported_arrival_at": reported_arrival,
        }
        if movement == "arrival":
            row.update(
                {"origin_icao": counterpart_icao, "arrival_status": item.get("status_raw")}
            )
            return "arrivals", row, lookups
        row.update(
            {
                "destination_icao": counterpart_icao,
                "departure_status": item.get("status_raw"),
            }
        )
        return "departures", row, lookups

    @staticmethod
    def collect_lookups(target: dict, lookups: dict) -> None:
        """Sammelt benötigte Stammdaten pro Schlüssel ohne doppelte Einträge."""
        for table, rows in lookups.items():
            key_field, _ = LOOKUP_SPECS[table]
            for row in rows:
                key = normalize_code(row.get(key_field))
                if not key:
                    continue
                clean = {field: value for field, value in row.items() if value is not None}
                clean[key_field] = key
                existing = target[table].setdefault(key, clean)
                for field, value in clean.items():
                    if value and not existing.get(field):
                        existing[field] = value

    def missing_lookups(self, collected: dict) -> dict[str, list[dict]]:
        """Filtert die gesammelten Stammdaten auf noch unbekannte Schlüssel."""
        return {
            table: [
                row
                for key, row in collected[table].items()
                if key not in self.references[reference_key]
            ]
            for table, (_, reference_key) in LOOKUP_SPECS.items()
        }

    def register_lookups(self, rows_by_table: dict[str, list[dict]]) -> None:
        """Übernimmt neu gespeicherte Schlüssel in den laufenden Mapping-Kontext."""
        for table, rows in rows_by_table.items():
            key_field, _ = LOOKUP_SPECS[table]
            known = {
                normalize_code(row.get(key_field)): row
                for row in self.reference_rows[table]
                if normalize_code(row.get(key_field))
            }
            for row in rows:
                key = normalize_code(row.get(key_field))
                if key and key not in known:
                    clean = dict(row)
                    clean[key_field] = key
                    self.reference_rows[table].append(clean)
                    known[key] = clean
        self.references = self._build_references(self.reference_rows)
