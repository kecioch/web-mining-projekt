# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy


class WebMiningScraperItem(scrapy.Item):
    # define the fields for your item here like:
    # name = scrapy.Field()
    pass



class AirportItem(scrapy.Item):
    rank = scrapy.Field()
    airport_name = scrapy.Field()
    passengers = scrapy.Field()
    freight_tons = scrapy.Field()
    aircraft_movements = scrapy.Field()
    area_ha = scrapy.Field()
    iata_code = scrapy.Field()
    icao_code = scrapy.Field()
    runways = scrapy.Field()
    elevation = scrapy.Field()
    opened = scrapy.Field()

    airport_url = scrapy.Field()
    list_source_url = scrapy.Field()
    detail_airport_name = scrapy.Field()
    detail_iata_code = scrapy.Field()
    detail_icao_code = scrapy.Field()
    latitude = scrapy.Field()
    longitude = scrapy.Field()
    location = scrapy.Field()
    operator = scrapy.Field()
    detail_elevation = scrapy.Field()
    detail_opened = scrapy.Field()
    detail_area = scrapy.Field()
    terminals = scrapy.Field()
    detail_scrape_status = scrapy.Field()
    source_url = scrapy.Field()


class AirlineItem(scrapy.Item):
    airline_name = scrapy.Field()
    country = scrapy.Field()
    iata_code = scrapy.Field()
    icao_code = scrapy.Field()
    callsign = scrapy.Field()
    airline_url = scrapy.Field()
    list_source_url = scrapy.Field()
    source_url = scrapy.Field()


class FlightMovementItem(scrapy.Item):
    observed_at_utc = scrapy.Field()
    service_date = scrapy.Field()
    movement_type = scrapy.Field()

    airport_name = scrapy.Field()
    airport_iata_code = scrapy.Field()
    airport_icao_code = scrapy.Field()
    counterpart_airport_name = scrapy.Field()
    counterpart_iata_code = scrapy.Field()
    counterpart_icao_code = scrapy.Field()

    origin_airport_name = scrapy.Field()
    origin_iata_code = scrapy.Field()
    origin_icao_code = scrapy.Field()
    destination_airport_name = scrapy.Field()
    destination_iata_code = scrapy.Field()
    destination_icao_code = scrapy.Field()

    flight_number = scrapy.Field()
    callsign = scrapy.Field()
    scheduled_time_local = scrapy.Field()
    local_timezone = scrapy.Field()
    status = scrapy.Field()
    status_raw = scrapy.Field()

    airline_name = scrapy.Field()
    departure_details_raw = scrapy.Field()
    arrival_details_raw = scrapy.Field()
    aircraft_model = scrapy.Field()
    aircraft_registration = scrapy.Field()
    terminal = scrapy.Field()
    gate = scrapy.Field()
    detail_fields = scrapy.Field()
    detail_scrape_status = scrapy.Field()

    details_url = scrapy.Field()
    source_url = scrapy.Field()
