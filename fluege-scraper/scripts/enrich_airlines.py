#!/usr/bin/env python3
"""Ergänzt vorhandene Airline-Stammdaten aus der IATA-Mitgliederliste."""

import math
import os
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from supabase_client import SupabaseClient


IATA_BASE_URL = "https://www.iata.org"
IATA_LIST_URL = f"{IATA_BASE_URL}/en/about/members/airline-list/"
REQUEST_DELAY_SECONDS = 0.25
ENRICHMENT_FIELDS = ("iata", "legal_name", "country", "website_url")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Erforderliche Umgebungsvariable fehlt: {name}")
    return value


def is_true(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def is_empty(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def create_iata_session() -> requests.Session:
    """Erstellt eine wiederverwendbare Sitzung mit browserähnlichen HTTP-Headern."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session


def get_html(session: requests.Session, url: str, params: dict | None = None) -> str:
    response = session.get(url, params=params, timeout=45)
    response.raise_for_status()
    time.sleep(REQUEST_DELAY_SECONDS)
    return response.text


def find_airline_table(soup: BeautifulSoup):
    for table in soup.select("table.datatable"):
        headings = [cell.get_text(" ", strip=True) for cell in table.select("thead td")]
        if "IATA Designator" in headings and "ICAO code" in headings:
            return table
    return None


def parse_list_page(html: str, wanted_icaos: set[str]) -> dict[str, dict]:
    """Extrahiert passende IATA-, ICAO- und Länderwerte aus einer Listenseite."""
    soup = BeautifulSoup(html, "html.parser")
    table = find_airline_table(soup)
    if table is None:
        raise RuntimeError("IATA-Airlinetabelle wurde nicht gefunden")

    matches: dict[str, dict] = {}
    for row in table.select("tbody tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 5:
            continue
        icao = cells[3].get_text(" ", strip=True).upper()
        if icao not in wanted_icaos:
            continue
        link = cells[0].find("a", href=True)
        matches[icao] = {
            "iata": cells[1].get_text(" ", strip=True).upper() or None,
            "country": cells[4].get_text(" ", strip=True) or None,
            "detail_url": urljoin(IATA_BASE_URL, link["href"]) if link else None,
        }
    return matches


def page_count(html: str) -> int:
    match = re.search(r"Found\s+([\d,]+)\s+airline members", html, re.IGNORECASE)
    if not match:
        raise RuntimeError("Anzahl der IATA-Mitglieder wurde nicht gefunden")
    total = int(match.group(1).replace(",", ""))
    return max(1, math.ceil(total / 10))


def load_iata_members(
    session: requests.Session, wanted_icaos: set[str]
) -> dict[str, dict]:
    """Durchläuft alle Mitgliederseiten und sammelt nur vorhandene DB-Airlines."""
    first_html = get_html(session, IATA_LIST_URL)
    matches = parse_list_page(first_html, wanted_icaos)

    for page in range(2, page_count(first_html) + 1):
        html = get_html(session, IATA_LIST_URL, params={"page": page})
        matches.update(parse_list_page(html, wanted_icaos))
    return matches


def parse_detail_page(html: str) -> dict:
    """Liest offiziellen Firmennamen und Webseite einer Airline-Detailseite."""
    soup = BeautifulSoup(html, "html.parser")
    values: dict[str, str] = {}
    for row in soup.select("table.datatable tbody tr"):
        heading = row.find("th")
        cell = row.find("td")
        if heading and cell:
            values[heading.get_text(" ", strip=True)] = cell.get_text(" ", strip=True)

    website_url = None
    for row in soup.select("table.datatable tbody tr"):
        heading = row.find("th")
        if heading and heading.get_text(" ", strip=True) == "Website":
            link = row.find("a", href=True)
            website_url = link["href"].strip() if link else None
            break

    return {
        "legal_name": values.get("Legal Name") or None,
        "website_url": website_url,
    }


def missing_values(airline: dict, source: dict) -> dict:
    return {
        field: source.get(field)
        for field in ENRICHMENT_FIELDS
        if is_empty(airline.get(field)) and not is_empty(source.get(field))
    }


def main() -> None:
    """Ergänzt ausschließlich fehlende Werte bereits vorhandener Airlines."""
    dry_run = is_true(os.environ.get("DRY_RUN", "true"))
    database = SupabaseClient(
        required_env("SUPABASE_URL"), required_env("SUPABASE_SERVICE_KEY")
    )
    airlines = database.fetch_all(
        "airlines",
        "icao,name,iata,legal_name,country,website_url",
        order="icao",
    )
    incomplete = [
        airline
        for airline in airlines
        if any(is_empty(airline.get(field)) for field in ENRICHMENT_FIELDS)
    ]
    wanted_icaos = {
        str(airline.get("icao") or "").strip().upper()
        for airline in incomplete
        if airline.get("icao")
    }

    session = create_iata_session()
    reference = load_iata_members(session, wanted_icaos) if wanted_icaos else {}

    # Detailseiten nur für vorhandene Airlines aufrufen, die dort noch Daten brauchen.
    for airline in incomplete:
        icao = str(airline.get("icao") or "").strip().upper()
        source = reference.get(icao)
        if not source or not source.get("detail_url"):
            continue
        if is_empty(airline.get("legal_name")) or is_empty(airline.get("website_url")):
            detail = parse_detail_page(get_html(session, source["detail_url"]))
            source.update(detail)

    updated = 0
    unchanged = 0
    not_found: list[str] = []

    for airline in incomplete:
        icao = str(airline.get("icao") or "").strip().upper()
        source = reference.get(icao)
        if not source:
            not_found.append(icao)
            continue
        values = missing_values(airline, source)
        if not values:
            unchanged += 1
            continue

        print(f"{icao}: ergänze {', '.join(values)}")
        if not dry_run:
            database.patch_equal("airlines", "icao", icao, values)
        updated += 1

    mode = "TESTLAUF - keine DB-Änderung" if dry_run else "DB aktualisiert"
    print(f"\nModus: {mode}")
    print(f"Geprüft: {len(airlines)}")
    print(f"Unvollständig: {len(incomplete)}")
    print(f"Ergänzbar: {updated}")
    print(f"Ohne neue Werte: {unchanged}")
    print(f"Nicht bei IATA gefunden: {len(not_found)}")
    if not_found:
        print("ICAO nicht gefunden: " + ", ".join(sorted(not_found)))


if __name__ == "__main__":
    main()
