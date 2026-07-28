import os
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import unquote

import scrapy
from scrapy_playwright.page import PageMethod

from web_mining_scraper.items import FlightMovementItem


class FlighteraFlightsSpider(scrapy.Spider):
    """Liest die aktuell angezeigten Flugbewegungen einer Flightera-Flughafenseite."""

    name = "flightera_flights"
    allowed_domains = ["flightera.net", "www.flightera.net"]

    custom_settings = {
        "LOG_LEVEL": "INFO",
    }

    @classmethod
    def update_settings(cls, settings):
        super().update_settings(settings)
        if os.environ.get("SHUB_JOBKEY"):
            return
        settings.set(
            "DOWNLOAD_HANDLERS",
            {
                "https": (
                    "scrapy_playwright.handler."
                    "ScrapyPlaywrightDownloadHandler"
                ),
            },
            priority="spider",
        )
        settings.set(
            "TWISTED_REACTOR",
            "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
            priority="spider",
        )
        settings.set("PLAYWRIGHT_BROWSER_TYPE", "chromium", priority="spider")
        settings.set(
            "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT",
            60_000,
            priority="spider",
        )

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider.browser_backend = (
            "zyte"
            if crawler.settings.get("ZYTE_API_KEY") or os.environ.get("SHUB_JOBKEY")
            else "playwright"
        )
        spider.logger.info(
            "Browser-Backend: %s",
            "Zyte API" if spider.browser_backend == "zyte" else "lokales Playwright",
        )
        return spider

    def __init__(
        self,
        airport_icao="EDDF",
        airport_slug="Frankfurt",
        movement_type="departure",
        start_date=None,
        end_date=None,
        start_time="00:00",
        end_time="23:59",
        max_pages=None,
        wait_seconds="10",
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.airport_icao = airport_icao.strip().upper()
        self.airport_slug = airport_slug.strip().strip("/")
        self.movement_type = movement_type.strip().lower()
        self.start_date = self.parse_date_argument(start_date, "start_date")
        self.end_date = self.parse_date_argument(end_date, "end_date")
        self.start_time = str(start_time).strip()
        self.end_time = str(end_time).strip()
        self.max_pages = (
            int(max_pages)
            if max_pages not in (None, "")
            else None
        )

        if not re.fullmatch(r"[A-Z0-9]{4}", self.airport_icao):
            raise ValueError("airport_icao muss ein vierstelliger ICAO-Code sein!")
        if not self.airport_slug:
            raise ValueError("airport_slug darf nicht leer sein!")
        if self.movement_type not in {"departure", "arrival"}:
            raise ValueError(
                "movement_type muss departure oder arrival sein!"
            )
        if bool(self.start_date) != bool(self.end_date):
            raise ValueError("start_date und end_date müssen gemeinsam angegeben werden!")
        if self.start_date and self.start_date > self.end_date:
            raise ValueError("start_date darf nicht nach end_date liegen!")
        if self.max_pages is not None and self.max_pages < 1:
            raise ValueError("max_pages muss mindestens 1 sein!")
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", self.start_time):
            raise ValueError("start_time muss HH:MM verwenden!")
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", self.end_time):
            raise ValueError("end_time muss HH:MM verwenden!")
        if self.start_date:
            self.start_datetime = datetime.fromisoformat(
                f"{self.start_date.isoformat()}T{self.start_time}"
            )
            self.end_datetime = datetime.fromisoformat(
                f"{self.end_date.isoformat()}T{self.end_time}"
            )
            if self.start_datetime > self.end_datetime:
                raise ValueError("Startzeitpunkt darf nicht nach dem Zielzeitpunkt liegen!")
        else:
            self.start_datetime = None
            self.end_datetime = None

        try:
            self.wait_milliseconds = max(0, int(float(wait_seconds) * 1000))
        except ValueError as error:
            raise ValueError("wait_seconds muss eine Zahl sein!") from error

        base_url = (
            "https://www.flightera.net/de/airport/"
            f"{self.airport_slug}/{self.airport_icao}"
        )

        # Immer die Einzeltabellen-Ansicht verwenden, nie die kombinierte
        # Flughafenansicht mit Ankünften und Abflügen.
        self.start_url = f"{base_url}/{self.movement_type}"
        if self.start_date:
            cursor = (
                f"{self.start_date.isoformat()}%20"
                f"{self.start_time.replace(':', '_')}"
            )
            self.start_url += f"?OffsetStart={cursor}"
        self.seen_details_urls = set()
        self.seen_timeline_urls = set()

    async def start(self):
        callback = (
            self.parse_movement_timeline
            if self.start_date
            else self.parse_current_movements
        )

        yield scrapy.Request(
            self.start_url,
            callback=callback,
            errback=self.handle_timeline_error if self.start_date else None,
            meta=self.browser_meta(page_number=1),
        )

    def parse_current_movements(self, response):
        items, _ = self.extract_movement_page(response, filter_period=False)
        for item in items:
            yield item

        self.logger.info(
            "%d aktuelle %s für %s gefunden",
            len(items),
            self.movement_type,
            self.airport_icao,
        )

    def parse_movement_timeline(self, response):
        if "/verify" in response.url:
            yield from self.retry_verification_page(response)
            return

        self.seen_timeline_urls.add(response.url)
        items, newest_scheduled_datetime = self.extract_movement_page(response)
        for item in items:
            yield item

        self.logger.info(
            "%d %s aus dem Zielzeitraum auf %s gefunden",
            len(items),
            self.movement_type,
            response.url,
        )

        if newest_scheduled_datetime and newest_scheduled_datetime > self.end_datetime:
            return

        current_page = response.meta.get("timeline_page", 1)
        if self.max_pages is not None and current_page >= self.max_pages:
            self.logger.info("Testgrenze max_pages=%d erreicht", self.max_pages)
            return

        later_href = self.find_later_flights_link(response)
        if not later_href or self.cursor_is_after_end_datetime(later_href):
            return

        next_url = response.urljoin(later_href)
        if next_url in self.seen_timeline_urls:
            later_href = self.advance_cursor_one_minute(later_href)
            if not later_href or self.cursor_is_after_end_datetime(later_href):
                return
            self.logger.warning(
                "Flightera-Cursor wiederholt sich; springe eine Minute weiter: %s",
                later_href,
            )

        yield response.follow(
            later_href,
            callback=self.parse_movement_timeline,
            errback=self.handle_timeline_error,
            meta=self.browser_meta(page_number=current_page + 1),
        )

    def extract_movement_page(self, response, filter_period=True):
        rows = response.css("table.flt-responsive-table tbody tr")
        if not rows:
            self.logger.error("Keine Bewegungstabelle auf %s gefunden", response.url)
            return [], None

        items = []
        newest_scheduled_datetime = None

        for row in rows:
            cells = row.css("td")
            if len(cells) < 8:
                continue

            details_href = cells[1].css("a::attr(href)").get()
            service_date_text = self.extract_service_date(details_href)
            if not service_date_text:
                continue
            service_date = date.fromisoformat(service_date_text)
            scheduled_departure = self.clean_text(
                cells[4].xpath(".//text()").getall()
            ) or None
            scheduled_datetime = self.combine_service_date_and_time(
                service_date, scheduled_departure
            )
            if scheduled_datetime:
                newest_scheduled_datetime = max(
                    newest_scheduled_datetime or scheduled_datetime,
                    scheduled_datetime,
                )
            if not scheduled_datetime:
                continue
            if filter_period and not (
                self.start_datetime <= scheduled_datetime <= self.end_datetime
            ):
                continue

            counterpart_links = cells[3].css('a[href*="/airport/"]')
            if not counterpart_links:
                continue
            counterpart = self.parse_airport_link(counterpart_links[0])

            if self.movement_type == "departure":
                origin = self.airport_data()
                destination = counterpart
            else:
                origin = counterpart
                destination = self.airport_data()

            status_raw = self.extract_status(cells[0])
            actual_departure = self.extract_reported_time(cells[5])
            departure_delay_text = self.extract_delay_text(cells[5])
            actual_arrival = self.extract_reported_time(cells[6])
            arrival_delay_text = self.extract_delay_text(cells[6])
            details_url = response.urljoin(details_href) if details_href else None
            if details_url and details_url in self.seen_details_urls:
                continue
            if details_url:
                self.seen_details_urls.add(details_url)

            items.append(FlightMovementItem(
                observed_at_utc=datetime.now(timezone.utc).isoformat(),
                service_date=service_date_text,
                movement_type=self.movement_type,
                airport_name=self.airport_slug,
                airport_icao_code=self.airport_icao,
                counterpart_airport_name=counterpart["name"],
                counterpart_iata_code=counterpart["iata_code"],
                counterpart_icao_code=counterpart["icao_code"],
                origin_airport_name=origin["name"],
                origin_iata_code=origin["iata_code"],
                origin_icao_code=origin["icao_code"],
                destination_airport_name=destination["name"],
                destination_iata_code=destination["iata_code"],
                destination_icao_code=destination["icao_code"],
                flight_number=self.clean_text(
                    cells[1].css("a::text").getall()
                ),
                scheduled_time_local=scheduled_departure,
                reported_time_local=(
                    actual_departure
                    if self.movement_type == "departure"
                    else actual_arrival
                ),
                delay_minutes=self.parse_delay_minutes(
                    departure_delay_text
                    if self.movement_type == "departure"
                    else arrival_delay_text
                ),
                delay_text=(
                    departure_delay_text
                    if self.movement_type == "departure"
                    else arrival_delay_text
                ),
                scheduled_departure_local=scheduled_departure,
                actual_departure_local=actual_departure,
                departure_delay_minutes=self.parse_delay_minutes(
                    departure_delay_text
                ),
                departure_delay_text=departure_delay_text,
                actual_arrival_local=actual_arrival,
                arrival_delay_minutes=self.parse_delay_minutes(
                    arrival_delay_text
                ),
                arrival_delay_text=arrival_delay_text,
                flight_duration_raw=self.clean_text(
                    cells[7].xpath(".//text()").getall()
                ) or None,
                status=self.normalize_status(status_raw),
                status_raw=status_raw,
                details_url=details_url,
                source_url=response.url,
            ))

        return items, newest_scheduled_datetime

    def find_later_flights_link(self, response):
        for link in response.css("a[href]"):
            text = self.clean_text(link.xpath(".//text()").getall()).casefold()
            if "later flights" in text or "spätere flüge" in text:
                return link.attrib.get("href")
        return None

    def cursor_is_after_end_datetime(self, href):
        decoded_href = unquote(href)
        match = re.search(
            r"OffsetStart=(\d{4}-\d{2}-\d{2})[ %](\d{2})_(\d{2})",
            decoded_href,
        )
        if not match:
            return False
        cursor_datetime = datetime.fromisoformat(
            f"{match.group(1)}T{match.group(2)}:{match.group(3)}"
        )
        return cursor_datetime > self.end_datetime

    def advance_cursor_one_minute(self, href, minutes=1):
        decoded_href = unquote(href)
        match = re.search(
            r"OffsetStart=(\d{4}-\d{2}-\d{2})[ %](\d{2})_(\d{2})",
            decoded_href,
        )
        if not match:
            return None
        cursor_datetime = datetime.fromisoformat(
            f"{match.group(1)}T{match.group(2)}:{match.group(3)}"
        ) + timedelta(minutes=minutes)
        return (
            f"/de/airport/{self.airport_slug}/{self.airport_icao}/"
            f"{self.movement_type}"
            f"?OffsetStart={cursor_datetime:%Y-%m-%d}%20{cursor_datetime:%H_%M}"
        )

    def browser_meta(self, page_number, retry_count=0):
        if self.browser_backend == "zyte":
            return self.zyte_api_meta(page_number, retry_count)
        return self.playwright_meta(page_number, retry_count)

    def zyte_api_meta(self, page_number, retry_count=0):
        return {
            "timeline_page": page_number,
            "timeline_retry": retry_count,
            "zyte_api": {
                "browserHtml": True,
                "sessionContext": [
                    {
                        "name": "flightera-airport",
                        "value": self.airport_icao,
                    },
                ],
                "actions": [
                    {
                        "action": "waitForSelector",
                        "selector": {
                            "type": "css",
                            "value": "table.flt-responsive-table",
                            "state": "attached",
                        },
                    },
                ],
            },
        }

    def retry_verification_page(self, response):
        retry_count = response.meta.get("verification_retry", 0)
        skip_count = response.meta.get("verification_skip_count", 0)
        requested_url = response.request.url
        if retry_count >= 3:
            if skip_count >= 6:
                self.logger.error(
                    "Flightera-Verifizierung auch nach 6 Cursor-Sprüngen nicht "
                    "überwunden: %s",
                    requested_url,
                )
                return

            later_href = self.advance_cursor_one_minute(requested_url)
            if not later_href or self.cursor_is_after_end_datetime(later_href):
                self.logger.info(
                    "Blockierter Cursor liegt am oder hinter dem Zeitraumende: %s",
                    requested_url,
                )
                return

            page_number = response.meta.get("timeline_page", 1)
            meta = self.browser_meta(page_number)
            meta["verification_skip_count"] = skip_count + 1
            if "zyte_api" in meta:
                meta["zyte_api"]["sessionContext"][0]["value"] = (
                    f"{self.airport_icao}-skip-{skip_count + 1}"
                )
            self.logger.warning(
                "Flightera-Verifizierung nach 4 Versuchen nicht überwunden; "
                "verschiebe den Cursor um 1 Minute und fahre fort (%d/6): %s",
                skip_count + 1,
                requested_url,
            )
            yield response.follow(
                later_href,
                callback=self.parse_movement_timeline,
                errback=self.handle_timeline_error,
                dont_filter=True,
                meta=meta,
            )
            return

        page_number = response.meta.get("timeline_page", 1)
        timeline_retry = response.meta.get("timeline_retry", 0)
        meta = self.browser_meta(page_number, timeline_retry)
        meta["verification_retry"] = retry_count + 1
        meta["verification_skip_count"] = skip_count
        if "zyte_api" in meta:
            meta["zyte_api"]["sessionContext"][0]["value"] = (
                f"{self.airport_icao}-verify-{retry_count + 1}-{skip_count}"
            )
        self.logger.warning(
            "Flightera-Verifizierungsseite erhalten; erneuter Versuch (%d/3): %s",
            retry_count + 1,
            requested_url,
        )
        yield response.request.replace(
            url=requested_url,
            dont_filter=True,
            meta=meta,
        )

    def playwright_meta(self, page_number, retry_count=0):
        return {
            "playwright": True,
            "timeline_page": page_number,
            "timeline_retry": retry_count,
            "playwright_context": f"timeline-{page_number}-retry-{retry_count}",
            "playwright_page_methods": [
                PageMethod(
                    "wait_for_selector",
                    "table.flt-responsive-table",
                    timeout=max(45_000, self.wait_milliseconds),
                ),
            ],
        }

    def handle_timeline_error(self, failure):
        request = failure.request
        retry_count = request.meta.get("timeline_retry", 0)
        page_number = request.meta.get("timeline_page", 1)
        if retry_count >= 2:
            self.logger.error(
                "Zeitfenster nach 3 Versuchen nicht erreichbar: %s; Ursache: %r\n%s",
                request.url,
                failure.value,
                failure.getTraceback(),
            )
            return

        self.logger.warning(
            "Zeitfenster wird erneut versucht (%d/2): %s",
            retry_count + 1,
            request.url,
        )
        return request.replace(
            dont_filter=True,
            meta=self.browser_meta(
                page_number=page_number,
                retry_count=retry_count + 1,
            ),
        )

    @staticmethod
    def combine_service_date_and_time(service_date, time_text):
        if not time_text:
            return None
        match = re.search(r"(\d{2}):(\d{2})", time_text)
        if not match:
            return None
        return datetime.combine(
            service_date,
            datetime.strptime(
                f"{match.group(1)}:{match.group(2)}", "%H:%M"
            ).time(),
        )

    def extract_status(self, cell):
        status = self.clean_text(
            cell.css("span.inline-flex.text-white::text").getall()
        )
        if status:
            return status
        return self.clean_text(cell.css("span::text").getall())

    def extract_reported_time(self, cell):
        value = self.clean_text(cell.css("span.font-semibold::text").getall())
        return value or None

    def airport_data(self):
        return {
            "name": self.airport_slug,
            "iata_code": None,
            "icao_code": self.airport_icao,
        }

    def parse_airport_link(self, link):
        href = link.attrib.get("href", "")
        text = self.clean_text(link.xpath(".//text()").getall())

        icao_match = re.search(r"/airport/[^/]+/([A-Z0-9]{4})(?:/|$)", href)
        codes_match = re.search(
            r"\(([A-Z0-9]{3})\s*/\s*([A-Z0-9]{4})\)", text
        )
        name = re.sub(r"\s*\([A-Z0-9]{3}\s*/\s*[A-Z0-9]{4}\)\s*$", "", text)

        return {
            "name": name or None,
            "iata_code": codes_match.group(1) if codes_match else None,
            "icao_code": (
                icao_match.group(1)
                if icao_match
                else codes_match.group(2) if codes_match else None
            ),
        }

    def extract_delay_text(self, cell):
        for text in cell.xpath(".//span//text()").getall():
            cleaned = text.strip()
            if re.search(r"\b(?:late|early)\b", cleaned, re.IGNORECASE):
                return cleaned
        return None

    @staticmethod
    def parse_delay_minutes(value):
        if not value:
            return None

        hours_match = re.search(r"(\d+)\s*h", value, re.IGNORECASE)
        minutes_match = re.search(r"(\d+)\s*min", value, re.IGNORECASE)
        minutes = (
            int(hours_match.group(1)) * 60 if hours_match else 0
        ) + (int(minutes_match.group(1)) if minutes_match else 0)

        if "early" in value.casefold():
            return -minutes
        return minutes

    @staticmethod
    def extract_service_date(href):
        if not href:
            return None
        match = re.search(r"/(\d{4}-\d{2}-\d{2})(?:[/?#]|$)", href)
        return match.group(1) if match else None

    @staticmethod
    def normalize_status(value):
        if not value:
            return None
        return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")

    @staticmethod
    def clean_text(texts):
        return " ".join(text.strip() for text in texts if text and text.strip())

    @staticmethod
    def parse_date_argument(value, argument_name):
        if value in (None, ""):
            return None
        try:
            return date.fromisoformat(str(value))
        except ValueError as error:
            raise ValueError(f"{argument_name} muss YYYY-MM-DD verwenden") from error
