import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import scrapy

from web_mining_scraper.items import FlightMovementItem


class BerlinAirportFlightsSpider(scrapy.Spider):
    """Liest Ankünfte und Abflüge aus der offiziellen BER-JSON-API."""

    name = "berlin_airport_flights"
    allowed_domains = ["berlin-airport.de", "ber.berlin-airport.de"]
    api_url = "https://ber.berlin-airport.de/api.flights.json"
    airport = {
        "name": "Berlin Brandenburg Airport",
        "iata": "BER",
        "icao": "EDDB",
    }

    def __init__(
        self,
        movement_type="both",
        service_date=None,
        start_time="00:00",
        end_time="23:59",
        max_pages="50",
        per_page="50",
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.movement_types = self.parse_movement_types(movement_type)
        self.service_date = self.parse_date(service_date) or datetime.now(
            ZoneInfo("Europe/Berlin")
        ).date().isoformat()
        self.start_time = self.parse_time(start_time, "start_time")
        self.end_time = self.parse_time(end_time, "end_time")
        self.max_pages = self.positive_int(max_pages, "max_pages")
        self.per_page = self.positive_int(per_page, "per_page")
        self.seen_flight_keys = {movement: set() for movement in self.movement_types}

        start = datetime.fromisoformat(f"{self.service_date}T{self.start_time}")
        end = datetime.fromisoformat(f"{self.service_date}T{self.end_time}")
        if start > end:
            raise ValueError("start_time darf nicht nach end_time liegen")
        # dateUntil ist exklusiv. Eine Minute nach end_time schließt die
        # gewünschte Endminute ein, ohne Flüge des Folgetags mitzunehmen.
        self.date_from = start.strftime("%Y-%m-%dT%H:%M")
        self.date_until = (end + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M")

    async def start(self):
        for movement_type in self.movement_types:
            yield self.make_request(movement_type, page=1)

    def make_request(self, movement_type, page):
        params = {
            "arrivalDeparture": "A" if movement_type == "arrival" else "D",
            "dateFrom": self.date_from,
            "dateUntil": self.date_until,
            "search": "",
            "lang": "de",
            "page": str(page),
            "terminal": "",
            "itemsPerPage": str(self.per_page),
        }
        return scrapy.Request(
            f"{self.api_url}?{urlencode(params)}",
            headers={
                "Accept": "application/json",
                "Referer": (
                    "https://ber.berlin-airport.de/de/fliegen/"
                    "abfluege-ankuenfte.html"
                ),
            },
            callback=self.parse_flights,
            cb_kwargs={"movement_type": movement_type, "page": page},
        )

    def parse_flights(self, response, movement_type, page):
        payload = response.json()
        if payload.get("error"):
            raise ValueError(
                "BER-API-Fehler: "
                f"{payload.get('message', 'unbekannter Fehler')}"
            )
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError("BER-Antwort enthält kein data.items-Array")

        emitted = 0
        for record in data["items"]:
            if not isinstance(record, dict):
                continue
            flight_key = self.flight_key(record, movement_type)
            if flight_key in self.seen_flight_keys[movement_type]:
                continue
            self.seen_flight_keys[movement_type].add(flight_key)
            emitted += 1
            yield self.build_item(record, movement_type, response.url)

        total_pages = self.safe_int(data.get("total_pages"))
        self.logger.info(
            "BER %s Seite %d/%s: %d Flüge",
            movement_type,
            page,
            total_pages if total_pages is not None else "?",
            emitted,
        )
        if total_pages is not None and page < total_pages and page < self.max_pages:
            yield self.make_request(movement_type, page + 1)
        elif total_pages is not None and page < total_pages:
            self.logger.warning(
                "BER %s durch max_pages=%d beendet; insgesamt gibt es %d Seiten",
                movement_type,
                self.max_pages,
                total_pages,
            )
        elif total_pages is not None:
            self.logger.info(
                "BER %s vollständig: Seite %d von %d erreicht",
                movement_type,
                page,
                total_pages,
            )

    @staticmethod
    def flight_key(record, movement_type):
        flight_id = record.get("id")
        if flight_id is not None:
            return "id", str(flight_id)
        scheduled = (
            record.get("arr_scheduled_time")
            if movement_type == "arrival"
            else record.get("dep_scheduled_time")
        ) or record.get("scheduled_time")
        return (
            "fallback",
            record.get("flight_number"),
            scheduled,
            record.get("dep_airport_iata"),
            record.get("arr_airport_iata"),
        )

    def build_item(self, record, movement_type, source_url):
        scheduled_departure = record.get("dep_scheduled_time") or (
            record.get("scheduled_time")
            if movement_type == "departure"
            else None
        )
        reported_departure = record.get("dep_estimated_time")
        scheduled_arrival = record.get("arr_scheduled_time") or (
            record.get("scheduled_time")
            if movement_type == "arrival"
            else None
        )
        reported_arrival = record.get("arr_estimated_time")
        scheduled_at_airport = (
            scheduled_arrival
            if movement_type == "arrival"
            else scheduled_departure
        )
        counterpart = {
            "name": (
                record.get("dep_airport_name")
                if movement_type == "arrival"
                else record.get("arr_airport_name")
            ),
            "iata": (
                record.get("dep_airport_iata")
                if movement_type == "arrival"
                else record.get("arr_airport_iata")
            ),
            "icao": None,
        }
        status_raw = record.get("flight_status_label")
        flight_id = record.get("id")

        return FlightMovementItem(
            observed_at_utc=datetime.now(timezone.utc).isoformat(),
            service_date=(
                self.extract_date(scheduled_at_airport) or self.service_date
            ),
            movement_type=movement_type,
            airport_name=self.airport["name"],
            airport_iata_code=self.airport["iata"],
            airport_icao_code=self.airport["icao"],
            counterpart_airport_name=counterpart["name"],
            counterpart_iata_code=counterpart["iata"],
            counterpart_icao_code=counterpart["icao"],
            via_airport_names=self.as_list(record.get("via_airport_names")),
            via_airport_iata_codes=self.as_list(
                record.get("via_airport_iata_codes")
            ),
            source_flight_id=(
                str(flight_id) if flight_id is not None else None
            ),
            flight_number=record.get("flight_number"),
            scheduled_departure_at=scheduled_departure,
            reported_departure_at=reported_departure,
            departure_delay_minutes=self.delay_minutes(
                scheduled_departure, reported_departure
            ),
            scheduled_arrival_at=scheduled_arrival,
            reported_arrival_at=reported_arrival,
            arrival_delay_minutes=self.delay_minutes(
                scheduled_arrival, reported_arrival
            ),
            flight_duration_raw=None,
            local_timezone="Europe/Berlin",
            status=self.normalize_status(record.get("flight_status_id") or status_raw),
            status_raw=status_raw,
            airline_name=record.get("airline_name"),
            airline_iata_code=record.get("airline_code"),
            codeshare_flight_numbers=self.as_list(record.get("code_shares")),
            aircraft_model=record.get("aircraft_type"),
            aircraft_registration=record.get("aircraft_reg") or None,
            terminal=record.get("terminal") or None,
            airport_hall=None,
            check_in_counter=record.get("checkin_counter") or None,
            gate=record.get("gate") or None,
            baggage_belts=self.as_list(record.get("arr_belt")),
            arrival_exit=record.get("arr_exit") or None,
            detail_fields={
                "flight_status_code": record.get("flight_status"),
                "flight_status_color": record.get("flight_status_color"),
                "gate_show_time": record.get("gate_show_time"),
                "passport_control": record.get("passport_control"),
                "map_urls": record.get("map_url"),
            },
            detail_scrape_status="not_requested",
            source_updated_at=record.get("updated_at"),
            details_url=(
                "https://ber.berlin-airport.de/de/fliegen/"
                f"abfluege-ankuenfte/flugdetails.html?flightId={flight_id}"
                if flight_id is not None
                else None
            ),
            source_url=source_url,
        )

    @staticmethod
    def parse_movement_types(value):
        value = str(value).strip().lower()
        aliases = {
            "arrival": "arrival",
            "arrivals": "arrival",
            "departure": "departure",
            "departures": "departure",
        }
        if value == "both":
            return "arrival", "departure"
        if value not in aliases:
            raise ValueError("movement_type muss arrival, departure oder both sein")
        return (aliases[value],)

    @staticmethod
    def parse_date(value):
        if value in (None, ""):
            return None
        if str(value).strip().lower() == "yesterday":
            return (
                datetime.now(ZoneInfo("Europe/Berlin")).date()
                - timedelta(days=1)
            ).isoformat()
        return date.fromisoformat(str(value)).isoformat()

    @staticmethod
    def parse_time(value, name):
        value = str(value).strip()
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError(f"{name} muss HH:MM verwenden")
        return value

    @staticmethod
    def positive_int(value, name):
        value = int(value)
        if value < 1:
            raise ValueError(f"{name} muss mindestens 1 sein")
        return value

    @staticmethod
    def safe_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def as_list(value):
        if value in (None, ""):
            return []
        return value if isinstance(value, list) else [value]

    @staticmethod
    def extract_date(value):
        if not value:
            return None
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            return None

    @staticmethod
    def parse_datetime(value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @classmethod
    def delay_minutes(cls, scheduled, reported):
        scheduled_dt = cls.parse_datetime(scheduled)
        reported_dt = cls.parse_datetime(reported)
        if not scheduled_dt or not reported_dt:
            return None
        return round((reported_dt - scheduled_dt).total_seconds() / 60)

    @staticmethod
    def normalize_status(value):
        if not value:
            return None
        return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")
