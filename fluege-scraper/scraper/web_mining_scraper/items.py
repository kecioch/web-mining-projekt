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

    airline_url = scrapy.Field()
    list_source_url = scrapy.Field()
    source_url = scrapy.Field()


class FlightMovementItem(scrapy.Item):
    observed_at_utc = scrapy.Field()  # Abrufzeitpunkt UTC
    service_date = scrapy.Field()  # Lokaler Flugtag
    movement_type = scrapy.Field()  # Bewegungsrichtung

    airport_name = scrapy.Field()  # Beobachteter Flughafen
    airport_iata_code = scrapy.Field()  # Flughafen-IATA-Code
    airport_icao_code = scrapy.Field()  # Flughafen-ICAO-Code

    counterpart_airport_name = scrapy.Field()  # Gegenflughafenname
    counterpart_iata_code = scrapy.Field()  # Gegenflughafen-IATA-Code
    counterpart_icao_code = scrapy.Field()  # Gegenflughafen-ICAO-Code

    via_airport_names = scrapy.Field()  # Zwischenstopp-Namen
    via_airport_iata_codes = scrapy.Field()  # Zwischenstopp-IATA-Codes

    source_flight_id = scrapy.Field()  # Quelleninterne Flug-ID
    flight_number = scrapy.Field()  # Öffentliche Flugnummer

    scheduled_departure_at = scrapy.Field()  # Geplanter Abflug
    reported_departure_at = scrapy.Field()  # Gemeldeter Abflug
    departure_delay_minutes = scrapy.Field()  # Abflugabweichung Minuten

    scheduled_arrival_at = scrapy.Field()  # Geplante Ankunft
    reported_arrival_at = scrapy.Field()  # Gemeldete Ankunft
    arrival_delay_minutes = scrapy.Field()  # Ankunftsabweichung Minuten

    flight_duration_raw = scrapy.Field()  # Flugdauer Originalwert
    local_timezone = scrapy.Field()  # Lokale Zeitzone

    status = scrapy.Field()  # Vereinheitlichter Status
    status_raw = scrapy.Field()  # Originaler Status

    airline_name = scrapy.Field()  # Fluggesellschaftsname
    airline_iata_code = scrapy.Field()  # Airline-IATA-Code
    codeshare_flight_numbers = scrapy.Field()  # Codeshare-Flugnummern

    aircraft_model = scrapy.Field()  # Flugzeugmodell
    aircraft_registration = scrapy.Field()  # Flugzeugkennzeichen

    terminal = scrapy.Field()  # Flughafenterminal
    airport_hall = scrapy.Field()  # Flughafenhalle
    check_in_counter = scrapy.Field()  # Check-in-Schalter
    gate = scrapy.Field()  # Flugsteig
    baggage_belts = scrapy.Field()  # Gepäckbänder
    arrival_exit = scrapy.Field()  # Ankunftsausgang

    detail_fields = scrapy.Field()  # Weitere Quelldaten
    detail_scrape_status = scrapy.Field()  # Status Detailabruf

    source_updated_at = scrapy.Field()  # Quellenaktualisierung
    details_url = scrapy.Field()  # Flugdetailseite
    source_url = scrapy.Field()  # Abrufquelle
