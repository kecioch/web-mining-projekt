import re
from datetime import date, datetime, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import scrapy

from web_mining_scraper.items import FlightMovementItem


class FrankfurtAirportFlightsSpider(scrapy.Spider):
    """Liest Flüge vom offiziellen JSON-Endpunkt des Frankfurt Airport."""

    name = "frankfurt_airport_flights"
    allowed_domains = ["frankfurt-airport.com", "www.frankfurt-airport.com"]
    custom_settings = {"LOG_LEVEL": "INFO"}
    # custom_settings = {"LOG_LEVEL": "WARNING"}
    api_url = "https://www.frankfurt-airport.com/de/_jcr_content.flights.json/filter"
    airport = {"name": "Frankfurt Airport", "iata": "FRA", "icao": "EDDF"}

    def __init__(self, movement_type="both", service_date=None,
                 start_time="00:00", end_time="23:59",
                 max_pages="20", per_page="50", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.movement_types = self.parse_movement_types(movement_type)
        self.service_date = self.parse_date(service_date)
        self.start_time = self.parse_time(start_time, "start_time")
        self.end_time = self.parse_time(end_time, "end_time")
        self.max_pages = self.positive_int(max_pages, "max_pages")
        self.per_page = min(self.positive_int(per_page, "per_page"), 50)

        self.start_datetime = None
        self.end_datetime = None
        if self.service_date:
            berlin_timezone = ZoneInfo("Europe/Berlin")
            self.start_datetime = datetime.fromisoformat(
                f"{self.service_date}T{self.start_time}"
            ).replace(tzinfo=berlin_timezone)
            self.end_datetime = datetime.fromisoformat(
                f"{self.service_date}T{self.end_time}"
            ).replace(tzinfo=berlin_timezone)
            if self.start_datetime > self.end_datetime:
                raise ValueError("start_time darf nicht nach end_time liegen")

    async def start(self):
        for movement_type in self.movement_types:
            yield self.make_request(movement_type, 1)

    def make_request(self, movement_type, page):
        params = {
                "flighttype": "arrivals" if movement_type == "arrival" else "departures",
                "perpage": str(self.per_page),
                "page": str(page),
                "lang": "de",
        }
        if self.start_datetime:
            params["time"] = self.format_api_time(self.start_datetime)
        return scrapy.Request(
            f"{self.api_url}?{urlencode(params)}",
            headers={"Accept": "application/json"},
            callback=self.parse_flights,
            cb_kwargs={"movement_type": movement_type, "page": page},
        )

    def parse_flights(self, response, movement_type, page):
        payload = response.json()
        records = payload.get("data")
        if not isinstance(records, list):
            raise ValueError("Frankfurt-Antwort enthält kein data-Array")

        reached_end = False
        emitted_count = 0
        filtered_count = 0
        for record in records:
            if not isinstance(record, dict):
                filtered_count += 1
                continue
            # Der Endpunkt mischt AIRail-/Express-Rail-Verbindungen in die
            # Flugliste. "P" kennzeichnet die tatsächlichen Passagierflüge.
            if record.get("typ") not in (None, "P"):
                filtered_count += 1
                continue
            if record.get("ac") == "TRS":
                filtered_count += 1
                continue
            item = self.build_item(record, movement_type, response.url)
            scheduled_datetime = self.parse_datetime(item.get("scheduled_time_local"))
            if self.start_datetime and scheduled_datetime:
                if scheduled_datetime < self.start_datetime:
                    filtered_count += 1
                    continue
                if scheduled_datetime > self.end_datetime:
                    reached_end = True
                    break
            emitted_count += 1
            yield item

        self.logger.info(
            "Frankfurt %s Seite %d: %d Flüge gespeichert, %d gefiltert",
            movement_type,
            page,
            emitted_count,
            filtered_count,
        )

        # Die Frankfurt-API liefert derzeit hasnext=false, obwohl maxpage und
        # direkte Requests auf die Folgeseiten gültig sind. Daher anhand der
        # tatsächlichen Seitennummer und maxpage fortsetzen.
        response_page = self.safe_int(payload.get("page")) or page
        max_page = self.safe_int(payload.get("maxpage"))
        has_more = bool(records) and (
            max_page is None or response_page < max_page
        )
        if not reached_end and has_more and page < self.max_pages:
            yield self.make_request(movement_type, page + 1)
        elif reached_end:
            self.logger.info(
                "Frankfurt %s beendet: Zeitraumende %s %s erreicht",
                movement_type,
                self.service_date,
                self.end_time,
            )
        elif page >= self.max_pages and has_more:
            self.logger.warning(
                "Frankfurt %s beendet: Sicherheitsgrenze max_pages=%d erreicht",
                movement_type,
                self.max_pages,
            )
        else:
            self.logger.info(
                "Frankfurt %s beendet: keine weitere API-Seite vorhanden",
                movement_type,
            )

    def build_item(self, record, movement_type, source_url):
        scheduled = self.normalize_datetime(self.first(
            record, "sched", "scheduled", "scheduledDate"
        ))
        actual = self.normalize_datetime(self.first(
            record, "actual", "acti", "esti", "estimated", "estimatedDate"
        ))
        counterpart = {
            "name": record.get("apname"),
            "iata": record.get("iata"),
            "icao": record.get("icao"),
        }
        origin = self.airport if movement_type == "departure" else counterpart
        destination = counterpart if movement_type == "departure" else self.airport
        delay = self.delay_minutes(scheduled, actual)
        status_raw = record.get("status")
        flight_id = record.get("id")
        overview = "ankuenfte" if movement_type == "arrival" else "abfluege"

        return FlightMovementItem(
            observed_at_utc=datetime.now(timezone.utc).isoformat(),
            service_date=self.extract_date(scheduled),
            movement_type=movement_type,
            airport_name=self.airport["name"],
            airport_iata_code=self.airport["iata"],
            airport_icao_code=self.airport["icao"],
            counterpart_airport_name=counterpart["name"],
            counterpart_iata_code=counterpart["iata"],
            counterpart_icao_code=counterpart["icao"],
            origin_airport_name=origin["name"],
            origin_iata_code=origin["iata"],
            origin_icao_code=origin["icao"],
            destination_airport_name=destination["name"],
            destination_iata_code=destination["iata"],
            destination_icao_code=destination["icao"],
            flight_number=record.get("fnr"),
            scheduled_time_local=scheduled,
            reported_time_local=actual,
            delay_minutes=delay,
            scheduled_departure_local=scheduled if movement_type == "departure" else None,
            actual_departure_local=actual if movement_type == "departure" else None,
            departure_delay_minutes=delay if movement_type == "departure" else None,
            scheduled_arrival_local=scheduled if movement_type == "arrival" else None,
            actual_arrival_local=actual if movement_type == "arrival" else None,
            arrival_delay_minutes=delay if movement_type == "arrival" else None,
            flight_duration_raw=record.get("duration"),
            local_timezone="Europe/Berlin",
            status=self.normalize_status(status_raw),
            status_raw=status_raw,
            airline_name=record.get("alname"),
            aircraft_model=record.get("ac"),
            aircraft_registration=record.get("reg"),
            terminal=record.get("terminal"),
            gate=record.get("gate"),
            detail_fields={
                "id": flight_id,
                "airline_iata_code": record.get("al"),
                "codeshares": record.get("cs") or [],
                "transport_type": record.get("typ"),
                "hall": record.get("halle"),
                "check_in": record.get("schalter"),
                "check_in_area": record.get("schalterarea"),
            },
            details_url=(
                "https://www.frankfurt-airport.com/de/fluege-und-airlines/"
                f"{overview}/flug.html/{flight_id}" if flight_id else None
            ),
            source_url=source_url,
        )

    @staticmethod
    def parse_movement_types(value):
        value = str(value).strip().lower()
        aliases = {"arrival": "arrival", "arrivals": "arrival",
                   "departure": "departure", "departures": "departure"}
        if value == "both":
            return "arrival", "departure"
        if value not in aliases:
            raise ValueError("movement_type muss arrival, departure oder both sein")
        return (aliases[value],)

    @staticmethod
    def parse_date(value):
        return date.fromisoformat(str(value)).isoformat() if value not in (None, "") else None

    @staticmethod
    def parse_time(value, name):
        value = str(value).strip()
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError(f"{name} muss HH:MM verwenden")
        return value

    @staticmethod
    def format_api_time(value):
        return (
            value.astimezone(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )

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
    def first(record, *keys):
        return next((record.get(key) for key in keys if record.get(key)), None)

    @staticmethod
    def extract_date(value):
        try:
            return date.fromisoformat(value[:10]).isoformat() if value else None
        except ValueError:
            return None

    @staticmethod
    def parse_datetime(value):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None

    @classmethod
    def normalize_datetime(cls, value):
        parsed = cls.parse_datetime(value)
        return parsed.isoformat(timespec="seconds") if parsed else value

    @classmethod
    def delay_minutes(cls, scheduled, actual):
        scheduled_dt, actual_dt = cls.parse_datetime(scheduled), cls.parse_datetime(actual)
        if not scheduled_dt or not actual_dt:
            return None
        return round((actual_dt - scheduled_dt).total_seconds() / 60)

    @staticmethod
    def normalize_status(value):
        return "_".join(str(value).casefold().split()) if value else None
