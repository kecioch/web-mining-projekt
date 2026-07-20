import re

import scrapy

from web_mining_scraper.items import AirlineItem


class AirlinesWikipediaSpider(scrapy.Spider):
    name = "airlines_wikipedia"
    allowed_domains = ["de.wikipedia.org"]
    start_urls = [
        "https://de.wikipedia.org/wiki/Liste_von_aktiven_Fluggesellschaften"
    ]

    def parse(self, response):
        # Passende Tabelle finden
        airline_tables = response.xpath(
            "//table[contains(concat(' ', normalize-space(@class), ' '), "
            "' wikitable ')][.//th[contains(normalize-space(.), 'IATA')] "
            "and .//th[contains(normalize-space(.), 'ICAO')] "
            "and .//th[contains(normalize-space(.), 'Herkunftsland')]]"
        )
        if not airline_tables:
            self.logger.error("Keine Airline-Tabelle auf %s gefunden", response.url)
            return

        rows = airline_tables[0].css("tr")
        self.logger.info("Airline-Tabelle mit %d Zeilen gefunden", len(rows))

        # Airlines zeilenweise auslesen
        for row in rows[1:]:
            cells = row.css("td")
            if len(cells) < 5:
                continue

            airline_name, airline_url = self.extract_airline_link(cells[0], response)
            if not airline_name:
                airline_name = self.clean_text(cells[0].css("::text").getall())

            yield AirlineItem(
                airline_name=airline_name,
                country=self.extract_country(cells[4]),
                iata_code=self.clean_code(self.cell_text(cells[1])),
                icao_code=self.clean_code(self.cell_text(cells[2])),
                callsign=self.clean_code(self.cell_text(cells[3])),
                airline_url=airline_url,
                list_source_url=response.url,
                source_url=response.url,
            )

    def extract_airline_link(self, cell, response):
        # Name und Detailseite ermitteln
        for link in cell.css("a[href]"):
            href = link.attrib.get("href", "")
            link_text = self.clean_text(link.css("::text").getall())
            if link_text and "/wiki/" in href:
                return link_text, response.urljoin(href)

        return None, None

    def extract_country(self, cell):
        # Herkunftsland auslesen
        for link in cell.css("a"):
            country = self.clean_text(link.css("::text").getall())
            if country:
                return self.clean_country(country)

        return self.clean_country(self.cell_text(cell))

    def cell_text(self, cell):
        return self.clean_text(
            cell.xpath(".//text()[not(ancestor::sup)]").getall()
        )

    @staticmethod
    def clean_text(texts):
        return " ".join(text.strip() for text in texts if text.strip())

    @staticmethod
    def clean_code(value):
        if not value:
            return None

        value = re.sub(r"\[.*?]", "", value)
        value = re.sub(r"\s+", " ", value).strip().upper()
        return value if any(char.isalnum() for char in value) else None

    @staticmethod
    def clean_country(value):
        if not value:
            return None

        value = re.sub(r"\[.*?]", "", value)
        value = re.sub(r"\s+", " ", value).strip(" ,")
        return value or None
