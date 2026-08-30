"""Löst fehlende Airport- und Airline-Codes über öffentliche Referenzdaten auf."""

import csv
import io
import math
import re
import time

import requests
from bs4 import BeautifulSoup

from flight_mapping_service import normalize_code, normalize_name


OURAIRPORTS_CSV_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
IATA_BASE_URL = "https://www.iata.org"
IATA_LIST_URL = f"{IATA_BASE_URL}/en/about/members/airline-list/"
REQUEST_DELAY_SECONDS = 0.25
ICAO_AIRPORT_RE = re.compile(r"^[A-Z]{4}$")
ICAO_AIRLINE_RE = re.compile(r"^[A-Z]{3}$")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def parse_float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def unique_index(rows: list[dict], field: str) -> dict[str, dict]:
    """Behält nur Schlüssel, die genau einem ICAO-Datensatz zugeordnet sind."""
    candidates: dict[str, dict[str, dict]] = {}
    for row in rows:
        value = normalize_name(row.get(field)) if field == "name" else normalize_code(row.get(field))
        icao = normalize_code(row.get("icao"))
        if value and icao:
            candidates.setdefault(value, {})[icao] = row
    return {
        value: next(iter(matches.values()))
        for value, matches in candidates.items()
        if len(matches) == 1
    }


class IataLookupService:
    """Die Klasse lädt Referenzquellen höchstens einmal und erzeugt sichere Stammdatentreffer."""

    def __init__(self):
        self._airports_by_iata: dict[str, dict] | None = None
        self._airlines_by_iata: dict[str, dict] | None = None
        self._airlines_by_icao: dict[str, dict] | None = None
        self._airlines_by_name: dict[str, dict] | None = None

    @staticmethod
    def _session() -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        return session

    def _load_airports(self) -> None:
        """Indexiert aktive OurAirports-Einträge mit eindeutigem IATA-Code."""
        response = requests.get(OURAIRPORTS_CSV_URL, timeout=90)
        response.raise_for_status()
        response.encoding = "utf-8"
        rows = []
        for source in csv.DictReader(io.StringIO(response.text)):
            if normalize_name(source.get("type")) == "closed":
                continue
            icao = normalize_code(source.get("gps_code"))
            if not icao or not ICAO_AIRPORT_RE.fullmatch(icao):
                ident = normalize_code(source.get("ident"))
                icao = ident if ident and ICAO_AIRPORT_RE.fullmatch(ident) else None
            iata = normalize_code(source.get("iata_code"))
            if not icao or not iata:
                continue
            rows.append(
                {
                    "icao": icao,
                    "iata": iata,
                    "name": (source.get("name") or "").strip() or None,
                    "latitude": parse_float(source.get("latitude_deg")),
                    "longitude": parse_float(source.get("longitude_deg")),
                    "website_url": (source.get("home_link") or "").strip() or None,
                }
            )
        self._airports_by_iata = unique_index(rows, "iata")

    @staticmethod
    def _airline_table(html: str):
        soup = BeautifulSoup(html, "html.parser")
        for table in soup.select("table.datatable"):
            headings = [cell.get_text(" ", strip=True) for cell in table.select("thead td")]
            if "IATA Designator" in headings and "ICAO code" in headings:
                return table
        raise RuntimeError("IATA-Airlinetabelle wurde nicht gefunden")

    @staticmethod
    def _page_count(html: str) -> int:
        match = re.search(r"Found\s+([\d,]+)\s+airline members", html, re.IGNORECASE)
        if not match:
            raise RuntimeError("Anzahl der IATA-Mitglieder wurde nicht gefunden")
        return max(1, math.ceil(int(match.group(1).replace(",", "")) / 10))

    @staticmethod
    def _get_html(session: requests.Session, params: dict | None = None) -> str:
        response = session.get(IATA_LIST_URL, params=params, timeout=45)
        response.raise_for_status()
        time.sleep(REQUEST_DELAY_SECONDS)
        return response.text

    def _load_airlines(self) -> None:
        """Indexiert die aktuelle IATA-Mitgliederliste nach IATA, ICAO und Name."""
        session = self._session()
        first_html = self._get_html(session)
        pages = [first_html]
        for page in range(2, self._page_count(first_html) + 1):
            pages.append(self._get_html(session, {"page": page}))

        rows = []
        for html in pages:
            table = self._airline_table(html)
            for source in table.select("tbody tr"):
                cells = source.find_all("td", recursive=False)
                if len(cells) < 5:
                    continue
                icao = normalize_code(cells[3].get_text(" ", strip=True))
                if not icao or not ICAO_AIRLINE_RE.fullmatch(icao):
                    continue
                rows.append(
                    {
                        "icao": icao,
                        "iata": normalize_code(cells[1].get_text(" ", strip=True)),
                        "name": cells[0].get_text(" ", strip=True) or None,
                        "country": cells[4].get_text(" ", strip=True) or None,
                    }
                )

        self._airlines_by_iata = unique_index(rows, "iata")
        self._airlines_by_icao = unique_index(rows, "icao")
        self._airlines_by_name = unique_index(rows, "name")

    def resolve(self, unresolved: dict) -> dict[str, list[dict]]:
        """Erzeugt Stammdaten nur für eindeutig aufgelöste fehlende Referenzen."""
        result = {"airports": [], "airlines": [], "aircraft": []}

        airport_requests = unresolved.get("airports", {})
        if airport_requests:
            if self._airports_by_iata is None:
                self._load_airports()
            result["airports"] = [
                self._airports_by_iata[iata]
                for iata in sorted(airport_requests)
                if iata in self._airports_by_iata
            ]

        airline_requests = unresolved.get("airlines", [])
        if airline_requests:
            if self._airlines_by_iata is None:
                self._load_airlines()
            matches: dict[str, dict] = {}
            for request in airline_requests:
                code = normalize_code(request.get("code"))
                name = normalize_name(request.get("name"))
                row = (
                    self._airlines_by_icao.get(code)
                    or self._airlines_by_iata.get(code)
                    or self._airlines_by_name.get(name)
                )
                if row:
                    matches[row["icao"]] = row
            result["airlines"] = [matches[key] for key in sorted(matches)]

        return result
