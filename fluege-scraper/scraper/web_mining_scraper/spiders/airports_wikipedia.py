import re

import scrapy

from web_mining_scraper.items import AirportItem


class AirportsWikipediaSpider(scrapy.Spider):
    name = "airports_wikipedia"
    allowed_domains = ["de.wikipedia.org"]
    start_urls = [
        "https://de.wikipedia.org/wiki/"
        "Liste_der_gr%C3%B6%C3%9Ften_Verkehrsflugh%C3%A4fen"
    ]

    def parse(self, response):
        # Flughafenliste finden
        tables = response.css("table.wikitable")
        if not tables:
            self.logger.error("Keine Flughafen-Tabelle auf %s gefunden", response.url)
            return

        rows = tables[0].css("tr")
        self.logger.info("Flughafen-Tabelle mit %d Zeilen gefunden", len(rows))

        # Flughäfen zeilenweise auslesen
        for row_index, row in enumerate(rows[2:], start=1):
            cells = row.css("td")
            if len(cells) < 10:
                continue

            values = [self.clean_text(cell.css("::text").getall()) for cell in cells]
            airport_url = self.extract_airport_url(cells[0], response)

            item = AirportItem(
                rank=row_index,
                airport_name=self.extract_airport_name(cells[0]),
                passengers=self.parse_int(values[1]),
                freight_tons=self.parse_int(values[2]),
                aircraft_movements=self.parse_int(values[3]),
                area_ha=self.parse_int(values[4]),
                iata_code=self.clean_code(values[5]),
                icao_code=self.clean_code(values[6]),
                runways=self.parse_int(values[7]),
                elevation=self.clean_note_text(values[8]),
                opened=self.clean_note_text(values[9]),
                airport_url=airport_url,
                list_source_url=response.url,
            )

            if not airport_url:
                item["detail_scrape_status"] = "missing_airport_url"
                self.logger.warning(
                    "Kein Wikipedia-Link für Flughafen %s gefunden",
                    item.get("airport_name"),
                )
                yield item
                continue

            # Wikipedia-Detailseite öffnen
            yield response.follow(
                airport_url,
                callback=self.parse_airport_details,
                errback=self.handle_detail_error,
                cb_kwargs={"item": item},
            )

    def parse_airport_details(self, response, item):
        # Infobox der Detailseite auslesen
        infoboxes = response.css("table.infobox")
        if not infoboxes:
            item["detail_scrape_status"] = "infobox_not_found"
            item["source_url"] = response.url
            yield item
            return
        infobox = infoboxes[0]

        infobox_values = self.extract_infobox_values(infobox)

        heading_cells = infobox.css("tr th[colspan]")
        detail_name = (
            self.clean_text(
                heading_cells[0].xpath(
                    ".//text()[not(ancestor::style) and not(ancestor::sup)]"
                ).getall()
            )
            if heading_cells
            else None
        )
        item["detail_airport_name"] = detail_name or self.clean_text(
            response.css("h1").xpath(".//text()").getall()
        )
        item["detail_iata_code"] = self.clean_code(
            self.find_infobox_value(infobox_values, "IATA-Code")
        )
        item["detail_icao_code"] = self.clean_code(
            self.find_infobox_value(infobox_values, "ICAO-Code")
        )
        item["latitude"] = self.extract_coordinate(response, "latitude")
        item["longitude"] = self.extract_coordinate(response, "longitude")
        item["location"] = self.find_infobox_value(
            infobox_values, "Entfernung vom Stadtzentrum", "Lage"
        )
        item["operator"] = self.find_infobox_value(infobox_values, "Betreiber")
        item["detail_elevation"] = self.find_infobox_value(
            infobox_values, "Höhe über MSL", "Höhe"
        )
        item["detail_opened"] = self.find_infobox_value(
            infobox_values, "Eröffnung", "Eröffnet"
        )
        item["detail_area"] = self.find_infobox_value(infobox_values, "Fläche")
        item["terminals"] = self.find_infobox_value(infobox_values, "Terminals")
        item["detail_scrape_status"] = (
            "success"
            if item.get("latitude") is not None and item.get("longitude") is not None
            else "coordinates_not_found"
        )
        item["source_url"] = response.url

        yield item

    def handle_detail_error(self, failure):
        item = failure.request.cb_kwargs["item"]
        item["detail_scrape_status"] = "request_failed"
        item["source_url"] = failure.request.url
        self.logger.warning(
            "Detailseite für %s konnte nicht geladen werden: %s",
            item.get("airport_name"),
            failure.value,
        )
        return item

    def extract_infobox_values(self, infobox):
        values = {}

        for row in infobox.css("tr"):
            cells = row.xpath("./th | ./td")
            if len(cells) != 2:
                continue

            label = self.clean_text(
                cells[0].xpath(".//text()[not(ancestor::sup)]").getall()
            )
            value = self.clean_text(
                cells[1].xpath(
                    ".//text()[not(ancestor::sup) and "
                    "not(ancestor::*[contains(@style, 'display:none')])]"
                ).getall()
            )
            if label and value:
                values[self.normalize_label(label)] = self.clean_note_text(value)

        return values

    def find_infobox_value(self, values, *labels):
        for label in labels:
            normalized_label = self.normalize_label(label)
            if normalized_label in values:
                return values[normalized_label]

        return None

    def extract_coordinate(self, response, coordinate):
        # Koordinaten auslesen
        value = response.css(
            f"table.infobox span.geo span.{coordinate}::text"
        ).get()
        if value is None:
            value = response.css(f"span.geo span.{coordinate}::text").get()

        parsed_value = self.parse_float(value)
        if parsed_value is not None:
            return parsed_value

        config_name = "lat" if coordinate == "latitude" else "lon"
        match = re.search(
            rf'"wgCoordinates"\s*:\s*\{{.*?"{config_name}"\s*:\s*(-?\d+(?:\.\d+)?)',
            response.text,
        )
        return self.parse_float(match.group(1)) if match else None

    def extract_airport_url(self, cell, response):
        links = cell.css("a[href]")

        for link in reversed(links):
            href = link.attrib.get("href", "")
            link_text = self.clean_text(link.css("::text").getall())
            if link_text and "/wiki/" in href and not href.startswith("#"):
                return response.urljoin(href)

        return None

    def extract_airport_name(self, cell):
        links = cell.css("a::text").getall()
        cleaned_links = [text.strip() for text in links if text.strip()]
        if cleaned_links:
            return cleaned_links[-1]
        return self.clean_text(cell.css("::text").getall())

    @staticmethod
    def clean_text(texts):
        return " ".join(text.strip() for text in texts if text.strip())

    @staticmethod
    def normalize_label(value):
        return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)

    def clean_code(self, value):
        if not value:
            return None

        value = value.strip().upper()
        return value if any(char.isalnum() for char in value) else None

    @staticmethod
    def clean_note_text(value):
        if not value:
            return None

        value = re.sub(r"\[.*?]", "", value).strip()
        return value if any(char.isalnum() for char in value) else None

    def parse_int(self, value):
        value = self.clean_note_text(value)
        if not value:
            return None

        number_match = re.search(r"\d+", value.replace(".", "").replace(",", ""))
        return int(number_match.group()) if number_match else None

    @staticmethod
    def parse_float(value):
        if not value:
            return None

        try:
            return float(value.strip().replace(",", "."))
        except (AttributeError, ValueError):
            return None
