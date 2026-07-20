"""Module defines the main entry point for the Apify Actor.

Module defines the main coroutine for the Apify Scrapy Actor, executed from the __main__.py file. The coroutine
processes the Actor's input and executes the Scrapy spider. Additionally, it updates Scrapy project settings by
applying Apify-related settings. Which includes adding a custom scheduler, retry middleware, and an item pipeline
for pushing data to the Apify dataset.

Customization:
--------------

Feel free to customize this file to add specific functionality to the Actor, such as incorporating your own Scrapy
components like spiders and handling Actor input. However, make sure you have a clear understanding of your
modifications. For instance, removing `apply_apify_settings` break the integration between Scrapy and Apify.

Documentation:
--------------

For an in-depth description of the Apify-Scrapy integration process, our Scrapy components, known limitations and
other stuff, please refer to the following documentation page: https://docs.apify.com/cli/docs/integrating-scrapy.
"""
from __future__ import annotations

from apify import Actor
from apify.scrapy import apply_apify_settings
from scrapy.crawler import AsyncCrawlerRunner

# Import your Scrapy spider here.
from .spiders.flightera_flights import FlighteraFlightsSpider as Spider

async def main() -> None:
    """Apify Actor main coroutine for executing the Scrapy spider."""
    async with Actor:
        # Retrieve and process Actor input.
        actor_input = await Actor.get_input() or {}
        proxy_config = actor_input.get('proxyConfiguration')

        # Apply Apify settings, which will override the Scrapy project settings.
        settings = apply_apify_settings(proxy_config=proxy_config)

        # Eingaben an den Flightera-Spider weitergeben
        crawler_runner = AsyncCrawlerRunner(settings)
        await crawler_runner.crawl(
            Spider,
            airport_icao=actor_input.get('airportIcao', 'EDDF'),
            airport_slug=actor_input.get('airportSlug', 'Frankfurt'),
            movement_type=actor_input.get('movementType', 'departure'),
            start_date=actor_input.get('startDate'),
            end_date=actor_input.get('endDate'),
            start_time=actor_input.get('startTime', '00:00'),
            end_time=actor_input.get('endTime', '23:59'),
            max_pages=actor_input.get('maxPages'),
            wait_seconds=actor_input.get('waitSeconds', 10),
        )
