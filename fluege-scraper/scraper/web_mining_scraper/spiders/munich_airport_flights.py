import re
from datetime import date, datetime, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import scrapy

from web_mining_scraper.items import FlightMovementItem


class MunichAirportFlightsSpider(scrapy.Spider):
    """Liest Flüge aus den serverseitigen HTML-Fragmenten des München Airport."""

    name = "munich_airport_flights"
    allowed_domains = ["munich-airport.de", "www.munich-airport.de"]
    custom_settings = {"LOG_LEVEL": "INFO"}
    base_url = "https://www.munich-airport.de/flightsearch"
    airport = {"name": "Munich Airport", "iata": "MUC", "icao": "EDDM"}

    def __init__(self, movement_type="both", service_date=None,
                 max_pages="50", per_page="50", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.movement_types = self.parse_movement_types(movement_type)
        self.service_date = self.parse_date(service_date)
        self.max_pages = self.positive_int(max_pages, "max_pages")
        # Der Flughafen liefert maximal 50 sichtbare Desktop-Zeilen je Seite.
        self.per_page = min(self.positive_int(per_page, "per_page"), 50)
        self.seen_flight_ids = {movement: set() for movement in self.movement_types}
        self.local_timezone = ZoneInfo("Europe/Berlin")

    async def start(self):
        for movement_type in self.movement_types:
            # Der München-Endpunkt nummeriert Seiten ab 0
            yield self.make_request(movement_type, 0)

    def make_request(self, movement_type, page):
        endpoint = "arrivals" if movement_type == "arrival" else "departures"
        params = {"page": str(page), "per_page": str(self.per_page),
                  "allow_pagination": "1"}
        if self.service_date:
            field = ("flight_search_presenter[flight_date_to_muc]"
                     if movement_type == "arrival"
                     else "flight_search_presenter[flight_date_from_muc]")
            params[field] = self.service_date
        return scrapy.Request(
            f"{self.base_url}/{endpoint}?{urlencode(params)}",
            headers={"Accept": "text/html"}, callback=self.parse_flights,
            cb_kwargs={"movement_type": movement_type, "page": page},
        )

    def parse_flights(self, response, movement_type, page):
        board = response.css(".fp-flight-board-body")
        if not board:
            raise ValueError(
                "Muenchen-Antwort enthaelt kein Flugplan-Fragment "
                f"(HTTP {response.status}, URL: {response.url})"
            )

        # Die Antwort enthält dieselben Flüge noch einmal in einer mobilen
        # Tabelle. Ausschließlich die Desktop-Tabelle hat die stabilen
        # Spaltenklassen, die build_item auswertet.
        rows = board.css(
            "table.fp-flights-table-large tbody > tr.fp-flight-item"
        )
        if not rows:
            rows = board.css("tr.fp-flight-item")
        emitted = 0
        for row in rows:
            # München liefert dieselben Flüge in Desktop- und Mobil-Markup
            flight_id = row.attrib.get("data-flight-id")
            if flight_id and flight_id in self.seen_flight_ids[movement_type]:
                continue
            if flight_id:
                self.seen_flight_ids[movement_type].add(flight_id)
            emitted += 1
            yield self.build_item(row, movement_type, response)

        total = self.safe_int(board.attrib.get("data-total-results"))
        if total and not rows:
            raise ValueError(
                "Muenchen meldet Fluege, aber das erwartete Tabellen-Markup "
                "wurde nicht gefunden"
            )
        displayed_page = page + 1
        has_more = (
            displayed_page * self.per_page < total
            if total is not None
            else emitted >= self.per_page
        )
        self.logger.info(
            "MUC %s Seite %d: %d eindeutige Flüge (gesamt laut Flughafen: %s)",
            movement_type,
            displayed_page,
            emitted,
            total if total is not None else "?",
        )
        if has_more and displayed_page < self.max_pages:
            yield self.make_request(movement_type, page + 1)
        elif has_more:
            self.logger.warning(
                "MUC %s durch max_pages=%d beendet; es existieren weitere Seiten",
                movement_type,
                self.max_pages,
            )
        else:
            self.logger.info(
                "MUC %s vollständig: letztes verfügbares Seitenergebnis erreicht",
                movement_type,
            )

    def build_item(self, row, movement_type, response):
        cell = lambda class_name: row.css(f".{class_name}")
        airline_cell, airport_cell = cell("fp-flight-airline"), cell("fp-flight-airport")
        number_cell, status_cell = cell("fp-flight-number"), cell("fp-flight-status")
        other_cell, muc_cell = cell("fp-flight-time-other"), cell("fp-flight-time-muc")
        area_cell = cell("fp-flight-area")

        number_raw = self.text(number_cell.xpath(".//text()").getall())
        flight_number, aircraft_model = self.parse_flight_number(number_raw)
        counterpart_name, counterpart_iata = self.parse_airport(
            self.text(airport_cell.xpath(".//text()").getall())
        )
        service_date = self.response_date(response)
        scheduled_raw, reported_raw = self.parse_times(muc_cell)
        # Die MUC-Spalte enthält nur HH:MM. Für die Datenbank ergänzen wir
        # den Flugtag und die Zeitzone des Flughafens.
        scheduled = self.to_muc_datetime(scheduled_raw, service_date)
        reported = self.to_muc_datetime(reported_raw, service_date)
        other_time = self.first_time(self.text(other_cell.xpath(".//text()").getall()))
        delay = self.delay_minutes(scheduled, reported)
        status_raw = self.text(status_cell.xpath(".//text()").getall()) or None
        airline_name = (airline_cell.css("img::attr(alt)").get()
                        or airline_cell.css(".info-content::text").get()
                        or self.text(airline_cell.xpath(".//text()").getall()) or None)
        counterpart = {"name": counterpart_name, "iata": counterpart_iata, "icao": None}
        origin = self.airport if movement_type == "departure" else counterpart
        destination = counterpart if movement_type == "departure" else self.airport
        details_href = row.css('a[href*="flugdetailseite"]::attr(href)').get()

        return FlightMovementItem(
            observed_at_utc=datetime.now(timezone.utc).isoformat(),
            service_date=service_date, movement_type=movement_type,
            airport_name=self.airport["name"], airport_iata_code=self.airport["iata"],
            airport_icao_code=self.airport["icao"],
            counterpart_airport_name=counterpart["name"],
            counterpart_iata_code=counterpart["iata"], counterpart_icao_code=None,
            origin_airport_name=origin["name"], origin_iata_code=origin["iata"],
            origin_icao_code=origin["icao"], destination_airport_name=destination["name"],
            destination_iata_code=destination["iata"], destination_icao_code=destination["icao"],
            flight_number=flight_number, scheduled_time_local=scheduled,
            reported_time_local=reported, delay_minutes=delay,
            scheduled_departure_local=scheduled if movement_type == "departure" else other_time,
            actual_departure_local=reported if movement_type == "departure" else None,
            departure_delay_minutes=delay if movement_type == "departure" else None,
            scheduled_arrival_local=scheduled if movement_type == "arrival" else other_time,
            actual_arrival_local=reported if movement_type == "arrival" else None,
            arrival_delay_minutes=delay if movement_type == "arrival" else None,
            local_timezone="Europe/Berlin", status=self.normalize_status(status_raw),
            status_raw=status_raw, airline_name=airline_name.strip() if airline_name else None,
            aircraft_model=aircraft_model,
            terminal=self.text(area_cell.xpath(".//text()").getall()) or None,
            detail_fields={"flight_id": row.attrib.get("data-flight-id")},
            details_url=response.urljoin(details_href) if details_href else None,
            source_url=response.url,
        )

    def response_date(self, response):
        if self.service_date:
            return self.service_date
        headline = self.text(response.css(".fp-flights-headline::text").getall())
        match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", headline)
        return f"{match.group(3)}-{match.group(2)}-{match.group(1)}" if match else None

    @classmethod
    def parse_times(cls, cell):
        value = cls.text(cell.xpath(".//text()").getall())
        times = re.findall(r"\b(?:[01]\d|2[0-3]):[0-5]\d\b", value)
        return times[0] if times else None, times[1] if len(times) > 1 else None

    @staticmethod
    def parse_flight_number(value):
        match = re.match(r"\s*([^()]+?)\s*(?:\(([^)]+)\))?\s*$", value or "")
        if not match:
            return value or None, None
        return match.group(1).strip(), match.group(2).strip() if match.group(2) else None

    @staticmethod
    def parse_airport(value):
        match = re.match(r"\s*(.*?)\s*\(([A-Z]{3})\)\s*$", value or "")
        return (match.group(1), match.group(2)) if match else (value or None, None)

    @staticmethod
    def first_time(value):
        match = re.search(r"\b(?:[01]\d|2[0-3]):[0-5]\d\b", value or "")
        return match.group(0) if match else None

    def to_muc_datetime(self, time_value, service_date):
        if not time_value or not service_date:
            return None
        try:
            return datetime.fromisoformat(
                f"{service_date}T{time_value}"
            ).replace(tzinfo=self.local_timezone).isoformat(timespec="seconds")
        except ValueError:
            return time_value

    @staticmethod
    def delay_minutes(scheduled, reported):
        if not scheduled or not reported:
            return None
        try:
            scheduled_dt = datetime.fromisoformat(scheduled)
            reported_dt = datetime.fromisoformat(reported)
        except ValueError:
            scheduled_dt = datetime.strptime(scheduled, "%H:%M")
            reported_dt = datetime.strptime(reported, "%H:%M")
        difference = round((reported_dt - scheduled_dt).total_seconds() / 60)
        return difference + 1440 if difference < -720 else difference - 1440 if difference > 720 else difference

    @staticmethod
    def text(values):
        return " ".join(value.strip() for value in values if value and value.strip())

    @staticmethod
    def normalize_status(value):
        return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_") if value else None

    @staticmethod
    def safe_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def parse_date(value):
        return date.fromisoformat(str(value)).isoformat() if value not in (None, "") else None

    @staticmethod
    def positive_int(value, name):
        value = int(value)
        if value < 1:
            raise ValueError(f"{name} muss mindestens 1 sein")
        return value

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
