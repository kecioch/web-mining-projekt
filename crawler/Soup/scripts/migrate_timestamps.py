#!/usr/bin/env python3
"""
Migrate old flight rows to the new timestamp schema.

The old scraper stored bare 'HH:MM' times plus a board timezone
(departure_time_tz / arrival_time_tz) and scraped_at. The new schema uses four
UTC timestamptz columns instead:

    scheduled_departure_at = planned takeoff   (origin)
    reported_departure_at  = actual takeoff    (origin)
    scheduled_arrival_at   = planned gate-in   (destination)
    reported_arrival_at    = actual gate-in    (destination)

What each old table can actually supply:

    departures rows:  start_plan / start_is -> scheduled/reported_departure_at
                      arrival_time (board)  -> reported_arrival_at
                      (no planned gate-in was captured -> scheduled_arrival_at stays NULL)

    arrivals rows:    gate_to_plan / gate_to_is -> scheduled/reported_arrival_at
                      departure_time (board)    -> reported_departure_at
                      (no planned takeoff was captured -> scheduled_departure_at stays NULL)

The date is inferred per row from scraped_at (the day whose HH:MM lands closest
to the scrape time), exactly like the live scraper does.

SAFETY: this script is DRY-RUN by default. It only writes when you pass --commit.

Examples:
    # preview everything
    python migrate_timestamps.py

    # only rows scraped before Aug 1st, preview
    python migrate_timestamps.py --older-than 2026-08-01

    # actually write those
    python migrate_timestamps.py --older-than 2026-08-01 --commit

    # just the arrivals table, first 50 rows, preview
    python migrate_timestamps.py --tables arrivals --limit 50
"""
import os
import re
import sys
import argparse
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv, find_dotenv
from supabase import create_client, Client

load_dotenv(find_dotenv())

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
supabase: Client = create_client(url, key)

PAGE = 1000  # supabase max rows per request


#### timezone handling ######################

TZ_ABBR = {
    "UTC": 0, "GMT": 0, "Z": 0,
 
    # Europe / Atlantic
    "WET": 0,   "WEST": 60,
    "CET": 60,  "CEST": 120,
    "EET": 120, "EEST": 180,
    "MSK": 180,
    "BST": 60,        # British Summer Time
    "IST": 60,        # Irish Standard Time
    "IDT": 180,       # Israel Daylight Time
    "TRT": 180,       # Turkey
    "AZOT": -60, "AZOST": 0,   # Azores
 
    # North America (standard / daylight)
    "EST": -300, "EDT": -240,
    "CST": -360, "CDT": -300,
                                
    "MST": -420, "MDT": -360,
    "PST": -480, "PDT": -420,
    "AKST": -540, "AKDT": -480,
    "HST": -600,
    "AST": -240, "ADT": -180,   
    "NST": -210, "NDT": -150,   # Newfoundland
 
    # Middle East / Asia
    "GST": 240,       # Gulf
    "PKT": 300,       # Pakistan
    "ICT": 420,       # Indochina
    "SGT": 480,       # Singapore
    "HKT": 480,       # Hong Kong
    "JST": 540,       # Japan
    "KST": 540,       # Korea
 
    # Africa
    "WAT": 60,        # West Africa
    "CAT": 120,       # Central Africa
    "SAST": 120,      # South Africa Standard
    "EAT": 180,       # East Africa
}

_UNKNOWN_TZ: set[str] = set()


def _tz_offset_minutes(tz: str | None) -> int | None:
    """CEST / '+03' / 'UTC+05:30' / '-0430' -> offset in minutes, else None."""
    if not tz:
        return None
    s = tz.strip().upper()
    if s[0] in "+-" or s.startswith("UTC") or s.startswith("GMT"):
        m = re.search(r"([+-])(\d{1,2})(?::?(\d{2}))?$", s)
        if m:
            sign = 1 if m.group(1) == "+" else -1
            return sign * (int(m.group(2)) * 60 + int(m.group(3) or 0))
    if s in TZ_ABBR:
        return TZ_ABBR[s]
    if s not in _UNKNOWN_TZ:
        _UNKNOWN_TZ.add(s)
        print(f"  ! unknown timezone '{tz}' -> left NULL (extend TZ_ABBR)")
    return None


def _hhmm(s) -> str | None:
    """Old stored value -> 'HH:MM' (defensive; values are already HH:MM)."""
    if not s:
        return None
    m = re.search(r"(\d{1,2}):(\d{2})", str(s))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def _combine_utc(hhmm: str | None, tz: str | None, ref_utc: datetime) -> datetime | None:
    """'HH:MM' + zone -> UTC datetime, dated to the day closest to ref_utc."""
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


def _fmt_ts(dt: datetime | None) -> str | None:
    return dt.strftime("%Y-%m-%d %H:%M:%S+00") if dt else None


def _delay_from(actual: datetime | None, planned: datetime | None) -> int | None:
    if actual is None or planned is None:
        return None
    diff = round((actual - planned).total_seconds() / 60)
    if diff > 720:
        diff -= 1440
    elif diff < -720:
        diff += 1440
    return diff


def _parse_ref(s) -> datetime | None:
    """scraped_at (ISO string) -> tz-aware UTC datetime, used for date inference."""
    if not s:
        return None
    txt = str(s).strip().replace("Z", "+00:00")
    for candidate in (txt, txt.split(".")[0], txt.split(".")[0] + "+00:00"):
        try:
            dt = datetime.fromisoformat(candidate)
            break
        except ValueError:
            dt = None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


#### migration logic ########################################################
TIMESTAMP_FIELDS = (
    "scheduled_departure_at", "reported_departure_at",
    "scheduled_arrival_at",   "reported_arrival_at",
)


def build_update(row: dict, table: str, recompute_delay: bool,
                 force: bool) -> tuple[dict, bool]:
    """Return (payload, had_source).

    A target column is added to `payload` only when BOTH hold:
      1. the source value needed to fill it is present (not NULL), and
      2. the target column isn't already filled  (unless --force).

    payload    -> {column: value} to write.
    had_source -> True if the old row had any usable source time at all
                  (lets the caller tell 'no source data' from 'already filled').
    """
    ref = _parse_ref(row.get("scraped_at"))
    if ref is None:
        return {}, False  # no reference date -> can't build a timestamp

    dep_tz = row.get("departure_time_tz")  # origin
    arr_tz = row.get("arrival_time_tz")    # destination

    # (target column, source datetime) pairs this table can supply
    arr_planned = arr_actual = None
    if table == "departures":
        candidates = [
            ("scheduled_departure_at", _combine_utc(_hhmm(row.get("start_plan")), dep_tz, ref)),   # planned takeoff
            ("reported_departure_at",  _combine_utc(_hhmm(row.get("start_is")),   dep_tz, ref)),   # actual takeoff
            ("reported_arrival_at",    _combine_utc(_hhmm(row.get("arrival_time")), arr_tz, ref)), # board arrival time
        ]
        # scheduled_arrival_at: no planned gate-in in old departures -> stays NULL
    elif table == "arrivals":
        arr_planned = _combine_utc(_hhmm(row.get("gate_to_plan")), arr_tz, ref)
        arr_actual = _combine_utc(_hhmm(row.get("gate_to_is")), arr_tz, ref)
        candidates = [
            ("scheduled_arrival_at",   arr_planned),                                                # planned gate-in
            ("reported_arrival_at",    arr_actual),                                                 # actual gate-in
            ("reported_departure_at",  _combine_utc(_hhmm(row.get("departure_time")), dep_tz, ref)),# board departure time
        ]
        # scheduled_departure_at: no planned takeoff in old arrivals -> stays NULL
    else:
        return {}, False

    had_source = any(dt is not None for _, dt in candidates)

    payload: dict = {}
    for col, dt in candidates:
        if dt is None:                                    # (1) source value is NULL -> skip
            continue
        if not force and row.get(col) not in (None, ""):  # (2) target already filled -> skip
            continue
        payload[col] = _fmt_ts(dt)

    # delay_minutes: only for arrivals, only when both gate-in times exist,
    # and only when the recomputed value actually differs from what's stored.
    if table == "arrivals" and recompute_delay:
        d = _delay_from(arr_actual, arr_planned)          # matches new scraper semantics
        if d is not None and d != row.get("delay_minutes"):
            payload["delay_minutes"] = d

    return payload, had_source


def migrate_table(table: str, older_than: str | None, newer_than: str | None,
                  limit: int | None, commit: bool, force: bool,
                  recompute_delay: bool) -> None:
    print(f"\n========== {table} ==========")
    if table not in ("departures", "arrivals"):
        print(f"! unknown table '{table}', skipping")
        return

    stats = dict(seen=0, updated=0, skip_migrated=0, skip_empty=0, skip_no_ref=0)
    previews = 0
    start = 0

    while True:
        q = supabase.table(table).select("*")
        if older_than:
            q = q.lt("scraped_at", older_than)
        if newer_than:
            q = q.gte("scraped_at", newer_than)
        # order by id => stable offset pagination (we don't change id or scraped_at)
        q = q.order("id").range(start, start + PAGE - 1)
        batch = q.execute().data
        if not batch:
            break

        for row in batch:
            if limit is not None and stats["seen"] >= limit:
                batch = []  # force outer loop to stop after this
                break
            stats["seen"] += 1

            if _parse_ref(row.get("scraped_at")) is None:
                stats["skip_no_ref"] += 1
                continue

            payload, had_source = build_update(row, table, recompute_delay, force)
            if not had_source:
                stats["skip_empty"] += 1      # old row had no usable source times
                continue
            if not payload:
                stats["skip_migrated"] += 1    # sources exist but targets already filled
                continue

            stats["updated"] += 1
            if previews < 5:
                previews += 1
                print(f"  {row.get('flight_no','?'):<10} "
                      f"scraped={row.get('scraped_at','?')}")
                for k, v in payload.items():
                    print(f"      {k:<24} <- {v}")

            if commit:
                supabase.table(table).update(payload).eq("id", row["id"]).execute()

        if not batch or len(batch) < PAGE:
            break
        if limit is not None and stats["seen"] >= limit:
            break
        start += PAGE

    mode = "WROTE" if commit else "would write (dry-run)"
    print(f"\n  {table}: seen {stats['seen']}, {mode} {stats['updated']}, "
          f"skipped {stats['skip_migrated']} already-migrated, "
          f"{stats['skip_empty']} no-source-times, "
          f"{stats['skip_no_ref']} no-scraped_at")


#### CLI ####################################################################

def _norm_date(s: str | None) -> str | None:
    """Accept 'YYYY-MM-DD' or full ISO; return an ISO string for the filter."""
    if not s:
        return None
    try:
        # date-only -> midnight UTC
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).isoformat()
        return _parse_ref(s).isoformat()
    except Exception:
        sys.exit(f"! could not parse date: {s!r}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill new timestamp columns from old time+tz data.")
    ap.add_argument("--older-than", metavar="DATE",
                    help="only migrate rows with scraped_at < DATE (YYYY-MM-DD or ISO)")
    ap.add_argument("--newer-than", metavar="DATE",
                    help="only migrate rows with scraped_at >= DATE (YYYY-MM-DD or ISO)")
    ap.add_argument("--tables", nargs="+", default=["departures", "arrivals"],
                    choices=["departures", "arrivals"],
                    help="which tables to migrate (default: both)")
    ap.add_argument("--limit", type=int, help="stop after N rows per table (for testing)")
    ap.add_argument("--commit", action="store_true",
                    help="actually write updates (default is dry-run)")
    ap.add_argument("--force", action="store_true",
                    help="re-migrate rows whose target columns are already filled")
    ap.add_argument("--no-recompute-delay", action="store_true",
                    help="do not recompute delay_minutes for arrivals from the new arrival times")
    args = ap.parse_args()

    older = _norm_date(args.older_than)
    newer = _norm_date(args.newer_than)

    print("Migration:", "COMMIT" if args.commit else "DRY-RUN (use --commit to write)")
    if older:
        print(f"  scraped_at <  {older}")
    if newer:
        print(f"  scraped_at >= {newer}")
    if args.limit:
        print(f"  limit {args.limit} rows/table")

    for table in args.tables:
        migrate_table(table, older, newer, args.limit, args.commit,
                      args.force, recompute_delay=not args.no_recompute_delay)

    if not args.commit:
        print("\nDry-run only. Re-run with --commit to apply.")


if __name__ == "__main__":
    main()