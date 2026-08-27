#!/usr/bin/env python3
import os
import re
import csv
import json
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse
from dotenv import load_dotenv, find_dotenv

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from supabase import create_client, Client

load_dotenv(find_dotenv())

#### Config ################################################################

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

NAV_TIMEOUT_MS = 30_000
SELECTOR_TIMEOUT_MS = 20_000
MAX_RETRIES = 1
HEADLESS = True
WAIT_UNTIL = "domcontentloaded"

DELAY_SECONDS = 1
DETAIL_LIMIT = None

TABLE_SELECTOR = "table.airportBoard"
DETAIL_SELECTOR = "h3.flightPageDataTableHeading, .flightPageSummaryTimes"

AIRPORTS = ["EDDF","EDDL","EDDK"] # ICAO codes
AIRPORT_URL = "https://de.flightaware.com/live/airport/{icao}"

#### DB ####################################################################

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
supabase: Client = create_client(url, key)

def save_supabase(icao, rows, fields, table, scraped_at, within_minutes=60, batch_size=500):
    if not rows:
        return

    airport = rows[0].get("airport_icao") # all rows in this call share one airport
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=within_minutes)).isoformat()

    q = (supabase.table(table)
         .select("id, flight_no, scraped_at")
         .gte("scraped_at", cutoff))
    if airport is not None:
        q = q.eq("airport_icao", airport)
    resp = q.order("scraped_at", desc=True).execute()

    recent = {}
    for r in resp.data:
        recent.setdefault(r["flight_no"], r["id"]) # first = newest (ordered desc)

    inserts, updated = [], 0
    for r in rows:
        record = {k: _nz(r.get(k)) for k in fields}
        record["scraped_at"] = scraped_at

        existing_id = recent.get(r["flight_no"])
        if existing_id is not None:
            supabase.table(table).update(record).eq("id", existing_id).execute()
            updated += 1
        else:
            inserts.append(record)

    for i in range(0, len(inserts), batch_size):
        chunk = inserts[i:i + batch_size]
        supabase.table(table).insert(chunk).execute()

    print(f"DB {icao} '{table}': {updated} updated, {len(inserts)} inserted")


def save_lookups(results):
    """Populate the lookup tables (airports, airlines, aircraft) from the
    full names captured while parsing so the fact tables can reference them
    by ICAO / code only."""
    airlines: dict[str, str] = {}   # icao -> name
    aircraft: dict[str, str] = {}   # code -> type
    airports: dict[str, str] = {}   # icao -> name

    airline_keys: set[str] = set()
    aircraft_keys: set[str] = set()
    airport_keys: set[str] = set()

    for icao, data in results.items():
        airport_keys.add(icao)  # the crawled airport itself
        for r in data["departures"] + data["arrivals"]:
            if r.get("airline_icao"):
                airline_keys.add(r["airline_icao"])
                if r.get("airline"):
                    airlines[r["airline_icao"]] = r["airline"]

            if r.get("aircraft_code"):
                aircraft_keys.add(r["aircraft_code"])
                if r.get("aircraft_type"):
                    aircraft[r["aircraft_code"]] = r["aircraft_type"]

            # destination (departures) or origin (arrivals)
            other_icao = r.get("destination_icao") or r.get("origin_icao")
            other_name = r.get("destination") or r.get("origin")
            if other_icao:
                airport_keys.add(other_icao)
                if other_name:
                    airports[other_icao] = other_name

    # upsert everything we have a name for (overwrites/refreshes the name)
    if airlines:
        supabase.table("airlines").upsert(
            [{"icao": k, "name": v} for k, v in airlines.items()],
            on_conflict="icao").execute()
    if aircraft:
        supabase.table("aircraft").upsert(
            [{"code": k, "type": v} for k, v in aircraft.items()],
            on_conflict="code").execute()
    if airports:
        supabase.table("airports").upsert(
            [{"icao": k, "name": v} for k, v in airports.items()],
            on_conflict="icao").execute()

    # make sure every referenced key exists
    miss_airlines = [{"icao": k} for k in airline_keys if k not in airlines]
    miss_aircraft = [{"code": k} for k in aircraft_keys if k not in aircraft]
    miss_airports = [{"icao": k} for k in airport_keys if k not in airports]
    if miss_airlines:
        supabase.table("airlines").upsert(
            miss_airlines, on_conflict="icao", ignore_duplicates=True).execute()
    if miss_aircraft:
        supabase.table("aircraft").upsert(
            miss_aircraft, on_conflict="code", ignore_duplicates=True).execute()
    if miss_airports:
        supabase.table("airports").upsert(
            miss_airports, on_conflict="icao", ignore_duplicates=True).execute()

    print(f"Lookups: {len(airlines)} airlines, {len(aircraft)} aircraft, "
          f"{len(airports)} airports (named)")


#### Helper ################################################################

def _clean(txt: str) -> str:
    return txt.replace("\xa0", " ").replace("\n", " ").strip() if txt else ""


def _nz(v):
    """Normalize empty strings to None, but keep 0 / negative numbers intact.
    An on-time flight with delay_minutes == 0 is stored, not dropped)."""
    return None if v is None or v == "" else v


def _to_time(s) -> str | None:
    """'19:44 CEST' or '17:14' -> 'HH:MM' (Postgres casts it to `time`), else None."""
    m = re.search(r"(\d{1,2}):(\d{2})", s or "")
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def _to_minutes(s) -> int | None:
    """'4 Minuten' / '-7' -> integer minutes, else None."""
    if s is None:
        return None
    m = re.search(r"-?\d+", str(s))
    return int(m.group()) if m else None


def _delay_minutes(actual: str, scheduled: str) -> str:
    """Calculate delays in minutes from two 'HH:MM'-Strings"""
    def to_min(s):
        m = re.search(r"(\d{1,2}):(\d{2})", s or "")
        return int(m.group(1)) * 60 + int(m.group(2)) if m else None
    a, s = to_min(actual), to_min(scheduled)
    if a is None or s is None:
        return ""
    diff = a - s
    # day changes
    p_a = re.search(r"\(\+(\d)\)", actual or "")
    p_s = re.search(r"\(\+(\d)\)", scheduled or "")
    diff += (int(p_a.group(1)) if p_a else 0) * 1440
    diff -= (int(p_s.group(1)) if p_s else 0) * 1440
    if diff < -720 and not p_a and not p_s:   # catch day changes without (+1)
        diff += 1440
    return str(diff)


def _split_time_tz(td) -> tuple[str, str]:
    tz_span = td.find("span", class_="tz")
    tz = _clean(tz_span.get_text()) if tz_span else ""
    time_txt = _clean(td.get_text()).replace(tz, "").strip()
    return time_txt, tz


#### Departure ################################################################

def parse_departures(html: str) -> list[dict]:
    """Extract all departures from HTML"""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"data-type": "departures"})
    if table is None:
        return []

    rows: list[dict] = []
    for tr in table.select("tbody tr[id^='Row_']"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 6:
            continue

        # 1. Flightnumber + Airline
        ident_span = tds[0].find("span")
        airline_raw = ident_span.get("title", "").strip() if ident_span else ""
        airline = airline_raw.split('"')[0].strip() or airline_raw
        ident_link = tds[0].find("a")
        flight_no = _clean(tds[0].get_text())
        detail_url = ident_link.get("href", "") if ident_link else ""
        m_icao = re.match(r"([A-Z]+)", flight_no)
        airline_icao = m_icao.group(1) if m_icao else ""

        # 2. Aircrafttype
        type_span = tds[1].find("span")
        ac_full = type_span.get("title", "").strip() if type_span else ""
        ac_code = _clean(tds[1].get_text())

        # 3. Destination: Name + ICAO (IATA only used to find the ICAO link)
        name_span = tds[2].find("span", itemprop="name")
        dest_name = _clean(name_span.get_text()) if name_span else ""
        iata_link = tds[2].find("a", itemprop="url")
        dest_icao = ""
        if iata_link and iata_link.get("href"):
            mm = re.search(r"/airport/([A-Z0-9]+)", iata_link["href"])
            if mm:
                dest_icao = mm.group(1)

        # 4. Times
        dep_time, dep_tz = _split_time_tz(tds[3])
        arr_time, arr_tz = _split_time_tz(tds[5])

        rows.append({
            "flight_no": flight_no,
            "airline": airline,          # -> airlines lookup table
            "airline_icao": airline_icao,
            "aircraft_code": ac_code,
            "aircraft_type": ac_full,    # -> aircraft lookup table
            "destination": dest_name,    # -> airports lookup table
            "destination_icao": dest_icao,
            "departure_time": _to_time(dep_time),
            "departure_time_tz": dep_tz,
            "arrival_time": _to_time(arr_time),
            "arrival_time_tz": arr_tz,
            "detail_url": detail_url,
            # Details properties will be filled later
            "departure_status": "",
            "gate_from_is": "",
            "gate_from_plan": "",
            "start_is": "",
            "start_plan": "",
            "rolltime": "",
            "delay_minutes": "",
        })
    return rows


#### Arrival ################################################################

def parse_arrivals(html: str) -> list[dict]:
    """Extract all arrivals from HTML"""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"data-type": "arrivals"})
    if table is None:
        return []

    rows: list[dict] = []
    for tr in table.select("tbody tr[id^='Row_']"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 6:
            continue

        # 1. Flightnumber + Airline
        ident_span = tds[0].find("span")
        airline_raw = ident_span.get("title", "").strip() if ident_span else ""
        airline = airline_raw.split('"')[0].strip() or airline_raw
        ident_link = tds[0].find("a")
        flight_no = _clean(tds[0].get_text())
        detail_url = ident_link.get("href", "") if ident_link else ""
        m_icao = re.match(r"([A-Z]+)", flight_no)
        airline_icao = m_icao.group(1) if m_icao else ""

        # 2. Aircrafttype
        type_span = tds[1].find("span")
        ac_full = type_span.get("title", "").strip() if type_span else ""
        ac_code = _clean(tds[1].get_text())

        # 3. Origin: Name + ICAO (IATA only used to find the ICAO link)
        name_span = tds[2].find("span", itemprop="name")
        orig_name = _clean(name_span.get_text()) if name_span else ""
        iata_link = tds[2].find("a", itemprop="url")
        orig_icao = ""
        if iata_link and iata_link.get("href"):
            mm = re.search(r"/airport/([A-Z0-9]+)", iata_link["href"])
            if mm:
                orig_icao = mm.group(1)

        # Times
        dep_time, dep_tz = _split_time_tz(tds[3])
        arr_time, arr_tz = _split_time_tz(tds[5])

        rows.append({
            "flight_no": flight_no,
            "airline": airline,          # -> airlines lookup table
            "airline_icao": airline_icao,
            "aircraft_code": ac_code,
            "aircraft_type": ac_full,    # -> aircraft lookup table
            "origin": orig_name,         # -> airports lookup table
            "origin_icao": orig_icao,
            "departure_time": _to_time(dep_time),
            "departure_time_tz": dep_tz,
            "arrival_time": _to_time(arr_time),
            "arrival_time_tz": arr_tz,
            "detail_url": detail_url,
            # Details properties will be filled later
            "arrival_status": "",
            "landing_is": "",
            "landing_plan": "",
            "gate_to_is": "",
            "gate_to_plan": "",
            "rolltime": "",
            "delay_minutes": "",
        })
    return rows


#### Detailspage ################################################################

def parse_detail_departure(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    out: dict = {}

    # Airline-ICAO from fleet link
    fleet = soup.find("a", href=re.compile(r"/live/fleet/"))
    if fleet:
        mm = re.search(r"/live/fleet/([A-Z0-9]+)", fleet["href"])
        if mm:
            out["airline_icao"] = mm.group(1)

    # Departure Status
    status = soup.select_one(".flightPageDepartureDelayStatus")
    if status:
        out["departure_status"] = _clean(status.get_text()).strip("()")

    # Departure Times
    dep_table = None
    for h3 in soup.select("h3.flightPageDataTableHeading"):
        if "Abflugzeiten" in _clean(h3.get_text()):
            dep_table = h3.find_next_sibling("div", class_="flightPageDataTable")
            break

    if dep_table:
        gate_is, gate_plan = _time_child(dep_table, "Verlassen des Gates")
        start_is, start_plan = _time_child(dep_table, "Start")
        out["gate_from_is"], out["gate_from_plan"] = _to_time(gate_is), _to_time(gate_plan)
        out["start_is"], out["start_plan"] = _to_time(start_is), _to_time(start_plan)

        for anc in dep_table.select(".flightPageDataAncillaryTextContainer .flightPageDataAncillaryText"):
            t = _clean(anc.get_text())
            if t.startswith("Rollzeit"):
                out["rolltime"] = _to_minutes(t.split(":", 1)[1])

        # delay is computed from the raw 'HH:MM (+n)' strings, then stored as int
        out["delay_minutes"] = _to_minutes(_delay_minutes(gate_is, gate_plan))

    return out


def parse_detail_arrival(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    out: dict = {}

    # Airline-ICAO from fleet link
    fleet = soup.find("a", href=re.compile(r"/live/fleet/"))
    if fleet:
        mm = re.search(r"/live/fleet/([A-Z0-9]+)", fleet["href"])
        if mm:
            out["airline_icao"] = mm.group(1)

    # Arrival Status
    status = soup.select_one(".flightPageArrivalDelayStatus")
    if status:
        out["arrival_status"] = _clean(status.get_text()).strip("()")

    # Arrival Times
    arr_table = None
    for h3 in soup.select("h3.flightPageDataTableHeading"):
        if "Ankunftszeiten" in _clean(h3.get_text()):
            arr_table = h3.find_next_sibling("div", class_="flightPageDataTable")
            break

    if arr_table:
        landing_is, landing_plan = _time_child(arr_table, "Landung")
        gate_is, gate_plan = _time_child(arr_table, "Ankunft am Gate")
        out["landing_is"], out["landing_plan"] = _to_time(landing_is), _to_time(landing_plan)
        out["gate_to_is"], out["gate_to_plan"] = _to_time(gate_is), _to_time(gate_plan)

        for anc in arr_table.select(
                ".flightPageDataAncillaryTextContainer .flightPageDataAncillaryText"):
            t = _clean(anc.get_text())
            if t.startswith("Rollzeit"):
                out["rolltime"] = _to_minutes(t.split(":", 1)[1])

        # delay is computed from the raw 'HH:MM (+n)' strings, then stored as int
        out["delay_minutes"] = _to_minutes(_delay_minutes(gate_is, gate_plan))

    return out


def _time_child(table, heading_text: str) -> tuple[str, str]:
    """Reads 'is' and 'plan' times from a time block"""
    for child in table.select(".flightPageDataTimesChild"):
        head = child.select_one(".flightPageDataActualTimeHeading")
        if head and heading_text.lower() in _clean(head.get_text()).lower():
            actual = child.select_one(".flightPageDataActualTimeText")
            ancil = child.select_one(".flightPageDataAncillaryText")
            actual_txt = _clean(actual.get_text()) if actual else ""
            sched_txt = ""
            if ancil:
                sched_txt = _clean(ancil.get_text()).replace("Planmäßig", "").strip()
            return actual_txt, sched_txt
    return "", ""


#### Load page (one browser for session) ################################################################

def _load(page, url: str, wait_selector: str) -> str:
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            page.goto(url, wait_until=WAIT_UNTIL, timeout=NAV_TIMEOUT_MS)
            page.wait_for_selector(wait_selector, timeout=SELECTOR_TIMEOUT_MS)
            return page.content()
        except PWTimeout:
            last_error = f"Timeout (Attempt {attempt}/{MAX_RETRIES})"
            # if attempt < MAX_RETRIES:
            #     time.sleep(1 * attempt)
    raise RuntimeError(last_error or "Loading failed")


def _enrich_details(page, base: str, rows: list[dict], detail_parser) -> None:
    """Crawls details page for each data entry from main page (for delay information)"""
    targets = rows if DETAIL_LIMIT is None else rows[:DETAIL_LIMIT]
    for i, row in enumerate(targets):
        if not row["detail_url"]:
            continue
        detail_url = urljoin(base, row["detail_url"])
        print(f"[{i + 1}/{len(targets)}] Detail: {row['flight_no']}")
        try:
            detail_html = _load(page, detail_url, DETAIL_SELECTOR)
            row.update(detail_parser(detail_html))
            print(f"    calculated delay: {row.get('delay_minutes', '') or '?'} Min.")
        except Exception as exc:
            print(f"    ! Error: {exc}")

        if i < len(targets) - 1:
            time.sleep(DELAY_SECONDS)


def crawl_airport(page, base: str, url: str) -> dict:
    """Crawl one airport using an already-open page."""
    print(f"Load main page: {url}")
    html = _load(page, url, TABLE_SELECTOR)

    departures = parse_departures(html)
    arrivals = parse_arrivals(html)
    print(f"Departures: {len(departures)} | Arrivals: {len(arrivals)}\n")

    print("--- Departure: Details ---")
    _enrich_details(page, base, departures, parse_detail_departure)
    print("\n--- Arrival: Details ---")
    _enrich_details(page, base, arrivals, parse_detail_arrival)

    return {"departures": departures, "arrivals": arrivals}


def crawl_all(icaos: list[str]) -> dict:
    """Crawl a list of airports with a single browser session."""
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            user_agent=USER_AGENT, locale="de-DE",
            viewport={"width": 1366, "height": 768},
        )
        page = context.new_page()
        page.set_default_timeout(NAV_TIMEOUT_MS)

        try:
            for icao in icaos:
                url = AIRPORT_URL.format(icao=icao)
                base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
                print(f"\n========== {icao} ==========")
                try:
                    data = crawl_airport(page, base, url)
                    # tag every row with the airport it came from
                    for r in data["departures"]:
                        r["airport_icao"] = icao
                    for r in data["arrivals"]:
                        r["airport_icao"] = icao
                    results[icao] = data
                except Exception as exc:
                    print(f"! {icao} failed: {exc}")
                    results[icao] = {"departures": [], "arrivals": []}
        finally:
            context.close()
            browser.close()
    return results


#### Save ################################################################

FIELDS_DEP = [
    "airport_icao", "flight_no", "airline_icao", "aircraft_code", "destination_icao",
    "departure_time", "departure_time_tz", "arrival_time", "arrival_time_tz",
    "departure_status", "gate_from_is", "gate_from_plan", "start_is", "start_plan",
    "rolltime", "delay_minutes",
]

FIELDS_ARR = [
    "airport_icao", "flight_no", "airline_icao", "aircraft_code","origin_icao",
    "departure_time", "departure_time_tz", "arrival_time", "arrival_time_tz",
    "arrival_status", "landing_is", "landing_plan", "gate_to_is", "gate_to_plan",
    "rolltime", "delay_minutes",
]


def save_csv(rows, fields, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fields})


def save_json(rows, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


#### MAIN ################################################################

def main(icaos: list[str]) -> None:
    results = crawl_all(icaos)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    scraped_at = datetime.now(timezone.utc).isoformat()

    # lookup tables first, so the foreign keys in departures/arrivals resolve
    save_lookups(results)

    for icao, data in results.items():
        if data["departures"]:
            # save_json(data["departures"], f"departures_{icao}_{stamp}.json")
            save_supabase(icao, data["departures"], FIELDS_DEP, "departures", scraped_at)
        if data["arrivals"]:
            # save_json(data["arrivals"], f"arrivals_{icao}_{stamp}.json")
            save_supabase(icao, data["arrivals"], FIELDS_ARR, "arrivals", scraped_at)


if __name__ == "__main__":
    main(AIRPORTS)