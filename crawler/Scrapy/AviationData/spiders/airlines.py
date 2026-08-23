import scrapy
from AviationData.items import AirlineItem, CountryItem


class AirlinesSpider(scrapy.Spider):
    name = "airlines"
    allowed_domains = ["de.wikipedia.org"]

    # REMARKS
    # B = Billigfluggesellschaft
    # C = Charterfluggesellschaft
    # P = Passagierfluggesellschaft mit Linienflügen und ggf. einigen Charterflügen
    # P+ = Passagier- und Charterfluggesellschaft
    # R = führt Regierungsflüge durch
    # S = sonstige Flüge, wie z. B. medizinische Dienste oder Nostalgieflüge
    # T = Frachtfluggesellschaft
    # T+ = Fracht- und Charterfluggesellschaft
    # U = Universal; Passagier sowie Fracht
    # U+ = Charter-, Passagier- und Frachtfluggesellschaft
    EXCLUDED_REMARK_FLAGS = {"R", "S", "T", "T+"}

    start_urls = [
        "https://de.wikipedia.org/wiki/Liste_von_aktiven_Fluggesellschaften"
    ]

    custom_settings = {
        "FEEDS": {
            "output/airline-list.json": {
                "format": "json",
                "encoding": "utf-8",
                "indent": 2,
                "overwrite": True,
                "item_classes": ["AviationData.items.AirlineItem"],
            },
            "output/country-list.json": {
                "format": "json",
                "encoding": "utf-8",
                "indent": 2,
                "overwrite": True,
                "item_classes": ["AviationData.items.CountryItem"],
            },

        },
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen_countries = {}

    def parse(self, response):
        rows = response.css("tbody#mwbg > tr")

        for row in rows:
            cells = row.css("td")

            if len(cells) < 7:
                continue

            name_cell = cells[0]
            iata_cell = cells[1]
            icao_cell = cells[2]
            callsign_cell = cells[3]
            country_cell = cells[4]
            remark_cell = cells[6]


            name = name_cell.css("a::text").get() or name_cell.xpath("string(.)").get()
            href = name_cell.css("a::attr(href)").get()
            link = response.urljoin(href) if href else None

            # Process country
            country_item = self._extract_country(country_cell, response)
            country_id = country_item["id"] if country_item else None
            if country_item and country_id not in self._seen_countries:
                self._seen_countries[country_id] = country_item
                yield country_item

            item = AirlineItem(
                name=self._clean(name),
                iata=self._clean(iata_cell.xpath("string(.)").get()),
                icao=self._clean(icao_cell.xpath("string(.)").get()),
                callsign=self._clean(callsign_cell.xpath("string(.)").get()),
                country_id=country_id,
                remark=self._clean(remark_cell.xpath("string(.)").get()),
                link=link,
            )

            if self._remark_excluded(item["remark"]):
                continue

            yield item

            # TODO: ADD DETAILS SCRAPER
            #
            # if link:
            #     yield scrapy.Request(
            #         url=link,
            #         callback=self.parse_airline_detail,
            #         meta={"item": item},
            #     )

    def parse_airline_detail(self, response):
        item = response.meta["item"]
        yield item

    def _extract_country(self, cell, response):
        link = cell.css("a:not(:has(img))").xpath("(.)[last()]")
        if not link:
            return None
 
        name = self._clean(link.css("::text").get())
        href = link.css("::attr(href)").get()
        if not name or not href:
            return None
 
        url = response.urljoin(href)
        country_id = url.rstrip("/").rsplit("/", 1)[-1] or name
 
        img_src = cell.css("img::attr(src)").get()
        img = response.urljoin(img_src) if img_src else None
 
        return CountryItem(id=country_id, name=name, link=url, flag_url=img)


    @staticmethod
    def _clean(value):
        """Remove whitespace and non-breaking-spaces."""
        if value is None:
            return None
        return value.replace("\xa0", " ").strip() or None
    
    @classmethod
    def _remark_excluded(cls, remark):
        if not remark or not cls.EXCLUDED_REMARK_FLAGS:
            return False
        tokens = remark.replace(",", " ").split()
        return any(token in cls.EXCLUDED_REMARK_FLAGS for token in tokens)