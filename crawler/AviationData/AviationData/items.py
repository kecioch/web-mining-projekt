# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy


class AirlineItem(scrapy.Item):
    name = scrapy.Field()
    iata = scrapy.Field()
    icao = scrapy.Field()
    callsign = scrapy.Field()
    country_id = scrapy.Field()
    remark = scrapy.Field()
    link = scrapy.Field()           # Wikipedia-link to airline

class CountryItem(scrapy.Item):
    id = scrapy.Field()
    name = scrapy.Field()
    link = scrapy.Field()           # Wikipedia-link for country
    flag_url = scrapy.Field()       # Flag-Image-URL
