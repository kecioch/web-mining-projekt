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

AIRPORTS = ["EDLW","EDDL","EDDK"] # ICAO codes
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


def _to_minutes(s) -> int | None:
    """'4 Minuten' / '-7' -> integer minutes, else None."""
    if s is None:
        return None
    m = re.search(r"-?\d+", str(s))
    return int(m.group()) if m else None


def _split_time_tz(td) -> tuple[str, str]:
    """Board cell -> (time_text, tz). Only the tz is used downstream (fallback)."""
    tz_span = td.find("span", class_="tz")
    tz = _clean(tz_span.get_text()) if tz_span else ""
    time_txt = _clean(td.get_text()).replace(tz, "").strip()
    return time_txt, tz


#### timezone handling ################################################################

# Abbreviation -> UTC offset in MINUTES.
# DST abbreviations already encode the offset (CEST=+2, CET=+1), so fixed
# values are correct for the abbreviation as given.
TZ_ABBR = {
    "UTC": 0, 
    "GMT": 0, 
    "Z": 0,
    "WET": 0,   
    "WEST": 60,
    "CET": 60,  
    "CEST": 120,
    "EET": 120, 
    "EEST": 180,
    "MSK": 180,
    "BST": 60,        # British Summer Time
    "IST": 60,        # Irish Standard Time
    "IDT": 180,       # Israel Daylight Time
    "TRT": 180,       # Turkey
    "AZOT": -60, "AZOST": 0,   # Azores
    "GST": 240,       # Gulf
}

_UNKNOWN_TZ: set[str] = set()


def _tz_offset_minutes(tz: str | None) -> int | None:
    """CEST / EEST / IDT / '+03' / 'UTC+05:30' / '-0430' -> offset in minutes, else None."""
    if not tz:
        return None
    s = tz.strip().upper()

    # numeric offset: +03, -05, +0530, +05:30, UTC+3, GMT+2 ...
    if s[0] in "+-" or s.startswith("UTC") or s.startswith("GMT"):
        m = re.search(r"([+-])(\d{1,2})(?::?(\d{2}))?$", s)
        if m:
            sign = 1 if m.group(1) == "+" else -1
            return sign * (int(m.group(2)) * 60 + int(m.group(3) or 0))

    if s in TZ_ABBR:
        return TZ_ABBR[s]

    if s not in _UNKNOWN_TZ:
        _UNKNOWN_TZ.add(s)
        print(f"  ! unknown timezone '{tz}' -> timestamp left NULL (extend TZ_ABBR)")
    return None


def _time_and_tz(raw: str | None) -> tuple[str | None, str | None]:
    """'13:09 CEST' -> ('13:09', 'CEST'); '17:14' -> ('17:14', None).
    Day markers like '(+1)' are stripped before the tz token is read."""
    if not raw:
        return None, None
    s = raw.replace("\xa0", " ")
    s = re.sub(r"\(.*?\)", " ", s)          # drop '(+1)' etc so it isn't read as an offset
    m = re.search(r"(\d{1,2}):(\d{2})", s)
    if not m:
        return None, None
    hhmm = f"{int(m.group(1)):02d}:{m.group(2)}"
    zm = re.search(r"[A-Za-z]{2,5}|[+-]\d{1,2}:?\d{0,2}", s[m.end():])
    tz = zm.group(0).strip() if zm else None
    return hhmm, tz


def _combine_utc(hhmm: str | None, tz: str | None, ref_utc: datetime) -> datetime | None:
    """'HH:MM' + zone -> UTC datetime. Date inferred as the day (yesterday/today/
    tomorrow) whose result is closest to the scrape time. Fine for a live board."""
    if not hhmm or not tz:
        return None
    m = re.search(r"(\d{1,2}):(\d{2})", hhmm)
    if not m:
        return None
    off = _tz_offset_minutes(tz)
    if off is None:
        return None

    tzinfo = timezone(timedelta(minutes=off))
    ref_local = ref_utc.astimezone(tzinfo)
    base = ref_local.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                             second=0, microsecond=0)
    best = min((base + timedelta(days=d) for d in (-1, 0, 1)),
               key=lambda dt: abs(dt - ref_local))
    return best.astimezone(timezone.utc)


def _combine_from_raw(raw: str | None, tz_fallback: str | None,
                      ref_utc: datetime) -> datetime | None:
    """Combine a detail time string using its own inline tz, board tz as fallback."""
    hhmm, tz = _time_and_tz(raw)
    if not hhmm:
        return None
    return _combine_utc(hhmm, tz or tz_fallback, ref_utc)


def _fmt_ts(dt: datetime | None) -> str | None:
    """UTC datetime -> '2026-08-29 11:09:00+00' (Postgres timestamptz)."""
    return dt.strftime("%Y-%m-%d %H:%M:%S+00") if dt else None


def _delay_from(actual: datetime | None, planned: datetime | None) -> int | None:
    """Minutes between two timestamps (positive = actual later than planned)."""
    if actual is None or planned is None:
        return None
    diff = round((actual - planned).total_seconds() / 60)
    if diff > 720:          # day-inference artifact
        diff -= 1440
    elif diff < -720:
        diff += 1440
    return diff


def add_event_timestamps(row: dict, kind: str, ref_utc: datetime) -> None:
    """Build the 4 timestamptz fields + delay_minutes for one row.

    Mapping (identical for departures and arrivals):
        scheduled_departure_at = Start  Planmäßig      (planned takeoff, at origin)
        reported_departure_at  = Start  actual         (actual takeoff, at origin)
        scheduled_arrival_at   = Gate-in Planmäßig     (planned gate-in, at destination)
        reported_arrival_at    = Gate-in actual        (actual gate-in, at destination)
        delay_minutes          = reported_arrival - scheduled_arrival
    """
    start_tz = row.get("departure_time_tz")   # takeoff is at the origin
    gate_tz  = row.get("arrival_time_tz")     # gate-in is at the destination

    dep_actual  = _combine_from_raw(row.get("start_is"),      start_tz, ref_utc)  # actual takeoff
    dep_planned = _combine_from_raw(row.get("start_plan"),    start_tz, ref_utc)  # planned takeoff
    arr_actual  = _combine_from_raw(row.get("gate_arr_is"),   gate_tz,  ref_utc)  # actual gate-in
    arr_planned = _combine_from_raw(row.get("gate_arr_plan"), gate_tz,  ref_utc)  # planned gate-in

    row["scheduled_departure_at"] = _fmt_ts(dep_planned)   # planned takeoff
    row["reported_departure_at"]  = _fmt_ts(dep_actual)    # actual takeoff
    row["scheduled_arrival_at"]   = _fmt_ts(arr_planned)   # planned gate-in
    row["reported_arrival_at"]    = _fmt_ts(arr_actual)    # actual gate-in
    row["delay_minutes"]          = _delay_from(arr_actual, arr_planned)
    row["rolltime"]               = row.get("rolltime_out") if kind == "dep" else row.get("rolltime_in")


#### Departure ################################################################

def parse_departures(html: str) -> list[dict]:
    """Extract all departures from the airport board."""
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

        # 3. Destination: Name + ICAO
        name_span = tds[2].find("span", itemprop="name")
        dest_name = _clean(name_span.get_text()) if name_span else ""
        iata_link = tds[2].find("a", itemprop="url")
        dest_icao = ""
        if iata_link and iata_link.get("href"):
            mm = re.search(r"/airport/([A-Z0-9]+)", iata_link["href"])
            if mm:
                dest_icao = mm.group(1)

        # 4. Timezones only (used as fallback for the detail times)
        _, dep_tz = _split_time_tz(tds[3])
        _, arr_tz = _split_time_tz(tds[5])

        rows.append({
            "flight_no": flight_no,
            "airline": airline,          # -> airlines lookup table
            "airline_icao": airline_icao,
            "aircraft_code": ac_code,
            "aircraft_type": ac_full,    # -> aircraft lookup table
            "destination": dest_name,    # -> airports lookup table
            "destination_icao": dest_icao,
            "departure_time_tz": dep_tz, # origin tz (fallback for Start)
            "arrival_time_tz": arr_tz,   # destination tz (fallback for gate-in)
            "detail_url": detail_url,
        })
    return rows


#### Arrival ################################################################

def parse_arrivals(html: str) -> list[dict]:
    """Extract all arrivals from the airport board."""
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

        # 3. Origin: Name + ICAO
        name_span = tds[2].find("span", itemprop="name")
        orig_name = _clean(name_span.get_text()) if name_span else ""
        iata_link = tds[2].find("a", itemprop="url")
        orig_icao = ""
        if iata_link and iata_link.get("href"):
            mm = re.search(r"/airport/([A-Z0-9]+)", iata_link["href"])
            if mm:
                orig_icao = mm.group(1)

        # Timezones only (used as fallback for the detail times)
        _, dep_tz = _split_time_tz(tds[3])
        _, arr_tz = _split_time_tz(tds[5])

        rows.append({
            "flight_no": flight_no,
            "airline": airline,          # -> airlines lookup table
            "airline_icao": airline_icao,
            "aircraft_code": ac_code,
            "aircraft_type": ac_full,    # -> aircraft lookup table
            "origin": orig_name,         # -> airports lookup table
            "origin_icao": orig_icao,
            "departure_time_tz": dep_tz, # origin tz (fallback for Start)
            "arrival_time_tz": arr_tz,   # destination tz (fallback for gate-in)
            "detail_url": detail_url,
        })
    return rows


#### Detailspage ################################################################

def _detail_time(soup, heading_text: str) -> tuple[str | None, str | None]:
    """Find the times-child whose heading contains `heading_text` and return
    (actual_raw, planned_raw), both including the tz suffix. Searches the whole
    page, so it works for the two-table and the single 'Flugzeiten' layout."""
    for child in soup.select(".flightPageDataTimesChild"):
        head = child.select_one(".flightPageDataActualTimeHeading")
        if not head or heading_text.lower() not in _clean(head.get_text()).lower():
            continue
        actual = child.select_one(".flightPageDataActualTimeText")
        ancil = child.select_one(".flightPageDataAncillaryText")
        actual_txt = _clean(actual.get_text()) if actual else ""
        sched_txt = ""
        if ancil:
            sched_txt = _clean(ancil.get_text()).replace("Planmäßig", "").strip()
        return (actual_txt or None), (sched_txt or None)
    return None, None


def parse_detail(html: str) -> dict:
    """Shared detail parser for both departures and arrivals. Reads the takeoff
    ('Start') and gate-in ('Ankunft am Gate', fallback 'Landung') blocks."""
    soup = BeautifulSoup(html, "html.parser")
    out: dict = {}

    # Airline-ICAO from fleet link (more reliable than the board prefix)
    fleet = soup.find("a", href=re.compile(r"/live/fleet/"))
    if fleet:
        mm = re.search(r"/live/fleet/([A-Z0-9]+)", fleet["href"])
        if mm:
            out["airline_icao"] = mm.group(1)

    # Statuses (each row keeps only the one its FIELDS list references)
    dstat = soup.select_one(".flightPageDepartureDelayStatus")
    if dstat:
        out["departure_status"] = _clean(dstat.get_text()).strip("()")
    astat = soup.select_one(".flightPageArrivalDelayStatus")
    if astat:
        out["arrival_status"] = _clean(astat.get_text()).strip("()")

    # Takeoff: present in both layouts. Fall back to gate-out if ever absent.
    start_is, start_plan = _detail_time(soup, "Start")
    if start_is is None and start_plan is None:
        start_is, start_plan = _detail_time(soup, "Verlassen des Gates")
    out["start_is"], out["start_plan"] = start_is, start_plan

    # Gate-in: two-table layout has 'Ankunft am Gate'; single 'Flugzeiten'
    # layout only has 'Landung', so fall back to it.
    gate_is, gate_plan = _detail_time(soup, "Ankunft am Gate")
    if gate_is is None and gate_plan is None:
        gate_is, gate_plan = _detail_time(soup, "Landung")
    out["gate_arr_is"], out["gate_arr_plan"] = gate_is, gate_plan

    # Rolltime: first 'Rollzeit' = taxi-out (departure), second = taxi-in (arrival)
    rolls = []
    for anc in soup.select(".flightPageDataAncillaryTextContainer .flightPageDataAncillaryText"):
        t = _clean(anc.get_text())
        if t.startswith("Rollzeit"):
            rolls.append(_to_minutes(t.split(":", 1)[1] if ":" in t else t))
    out["rolltime_out"] = rolls[0] if len(rolls) >= 1 else None
    out["rolltime_in"]  = rolls[1] if len(rolls) >= 2 else None

    return out


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
    raise RuntimeError(last_error or "Loading failed")


def _enrich_details(page, base: str, rows: list[dict]) -> None:
    """Crawl the detail page for each row (start / gate-in times)."""
    targets = rows if DETAIL_LIMIT is None else rows[:DETAIL_LIMIT]
    for i, row in enumerate(targets):
        if not row["detail_url"]:
            continue
        detail_url = urljoin(base, row["detail_url"])
        print(f"[{i + 1}/{len(targets)}] Detail: {row['flight_no']}")
        try:
            detail_html = _load(page, detail_url, DETAIL_SELECTOR)
            row.update(parse_detail(detail_html))
            print(f"    start {row.get('start_is') or '?'} / gate {row.get('gate_arr_is') or '?'}")
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
    _enrich_details(page, base, departures)
    print("\n--- Arrival: Details ---")
    _enrich_details(page, base, arrivals)

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
    "departure_status", "rolltime", "delay_minutes",
    "scheduled_departure_at", "reported_departure_at",
    "scheduled_arrival_at", "reported_arrival_at",
]

FIELDS_ARR = [
    "airport_icao", "flight_no", "airline_icao", "aircraft_code", "origin_icao",
    "arrival_status", "rolltime", "delay_minutes",
    "scheduled_departure_at", "reported_departure_at",
    "scheduled_arrival_at", "reported_arrival_at",
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
    scraped_dt = datetime.now(timezone.utc)          # reference for date inference
    scraped_at = scraped_dt.isoformat()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # derive the 4 timestamptz fields + delay before saving
    for icao, data in results.items():
        for r in data["departures"]:
            add_event_timestamps(r, "dep", scraped_dt)
        for r in data["arrivals"]:
            add_event_timestamps(r, "arr", scraped_dt)

    # lookup tables first, so the foreign keys resolve
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