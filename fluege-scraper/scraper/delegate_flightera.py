"""Flightera für Flughäfen aus den Wikipedia-Stammdaten seriell starten.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path


SCRAPER_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = SCRAPER_ROOT.parent
DEFAULT_AIRPORTS = PROJECT_ROOT / "data/output/airports_wikipedia_details.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data/output/flightera_hourly"
VERIFY_MARKERS = ("/verify", "verifizierungsseite", "verification", "captcha")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ruft flightera_flights langsam und seriell pro Flughafen auf."
    )
    parser.add_argument("--airports-file", type=Path, default=DEFAULT_AIRPORTS)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--at",
        type=datetime.fromisoformat,
        help="Stunde als lokale ISO-Zeit, z. B. 2026-07-20T18:00 (Standard: jetzt).",
    )
    parser.add_argument(
        "--max-airports",
        type=int,
        default=5,
        help="Sicherheitslimit pro Lauf; 0 verarbeitet alle (Standard: 5).",
    )
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--min-pause", type=float, default=5.0)
    parser.add_argument("--max-pause", type=float, default=10.0)
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=10.0,
        help="Wartezeit des Browsers auf die Flugtabelle.",
    )
    parser.add_argument(
        "--slug-overrides",
        type=Path,
        help='Optionale JSON-Datei, z. B. {"EDDF": "Frankfurt"}.',
    )
    parser.add_argument("--seed", type=int, help="Seed fuer reproduzierbare Pausen.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.max_airports < 0 or args.offset < 0:
        parser.error("--max-airports und --offset duerfen nicht negativ sein")
    if args.min_pause < 0 or args.max_pause < args.min_pause:
        parser.error("Pausen muessen >= 0 sein und max-pause >= min-pause")
    if args.wait_seconds < 0:
        parser.error("--wait-seconds darf nicht negativ sein")
    return args


def load_airports(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"Stammdaten nicht gefunden: {path}")

    with path.open(encoding="utf-8-sig") as handle:
        value = json.load(handle)

    if not isinstance(value, list):
        raise ValueError(f"Stammdaten müssen ein JSON-Array enthalten: {path}")

    records: list[dict] = []
    for index, record in enumerate(value):
        if not isinstance(record, dict):
            print(f"WARN: Eintrag {index} ist kein JSON-Objekt und wird übersprungen")
            continue
        icao = str(record.get("detail_icao_code") or record.get("icao_code") or "")
        if re.fullmatch(r"[A-Za-z0-9]{4}", icao):
            record["_icao"] = icao.upper()
            records.append(record)
        else:
            print(f"WARN: Eintrag {index} ohne gültigen ICAO-Code wird übersprungen")
    return records


def load_overrides(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    with path.open(encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(slug, str) for key, slug in value.items()
    ):
        raise ValueError("Slug-Overrides müssen ein JSON-Objekt aus ICAO: Slug sein")
    return {key.upper(): slug.strip().strip("/") for key, slug in value.items()}


def make_slug(record: dict, overrides: dict[str, str]) -> str:
    icao = record["_icao"]
    if overrides.get(icao):
        return overrides[icao]
    name = str(record.get("airport_name") or record.get("detail_airport_name") or icao)
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"\b(?:international\s+)?airport\b", "", name, flags=re.I)
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-") or icao


def python_executable() -> str:
    local_python = PROJECT_ROOT / ".venv/Scripts/python.exe"
    return str(local_python if local_python.is_file() else Path(sys.executable))


def append_manifest(path: Path, entry: dict) -> None:
    entries = []
    if path.is_file():
        with path.open(encoding="utf-8") as handle:
            entries = json.load(handle)
        if not isinstance(entries, list):
            raise ValueError(f"Manifest muss ein JSON-Array enthalten: {path}")
    entries.append(entry)
    path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    randomizer = random.Random(args.seed)
    airports = load_airports(args.airports_file)
    overrides = load_overrides(args.slug_overrides)
    selected = airports[args.offset :]
    if args.max_airports:
        selected = selected[: args.max_airports]
    if not selected:
        print("Keine Flughäfen für diesen Lauf ausgewählt.")
        return 0

    # Ein Lauf verwendet für alle Flughäfen dasselbe, lokale Zeitfenster.
    target = (args.at or datetime.now().astimezone()).replace(minute=0, second=0, microsecond=0)
    date_text = target.date().isoformat()
    start_time = target.strftime("%H:00")
    end_time = target.strftime("%H:59")
    run_dir = args.output_root / target.strftime("%Y-%m-%d/%H00")
    manifest = run_dir / "manifest.json"
    if not args.dry_run:
        run_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"Plane {len(selected)} Flughafen/Flughäfen für {date_text} "
        f"{start_time}-{end_time}; Ausgabe: {run_dir}"
    )

    for index, airport in enumerate(selected, 1):
        icao = airport["_icao"]
        slug = make_slug(airport, overrides)
        output_file = run_dir / f"{icao}.json"
        log_file = run_dir / f"{icao}.log"
        partial_file = run_dir / f".{icao}.part.json"

        if output_file.exists():
            print(f"[{index}/{len(selected)}] {icao}: bereits vorhanden, übersprungen")
            continue

        command = [
            python_executable(), "-m", "scrapy", "crawl", "flightera_flights",
            "-a", f"airport_icao={icao}", "-a", f"airport_slug={slug}",
            "-a", "movement_type=departure", "-a", f"start_date={date_text}",
            "-a", f"end_date={date_text}", "-a", f"start_time={start_time}",
            "-a", f"end_time={end_time}", "-a", "max_pages=1",
            "-a", f"wait_seconds={args.wait_seconds:g}",
            "-s", "CONCURRENT_REQUESTS_PER_DOMAIN=1", "-s", "DOWNLOAD_DELAY=5",
            "-s", "RANDOMIZE_DOWNLOAD_DELAY=True", "-O", str(partial_file),
        ]
        print(f"[{index}/{len(selected)}] {icao} ({slug})")
        if args.dry_run:
            print("  " + subprocess.list2cmdline(command))
            continue

        started_at = datetime.now().astimezone().isoformat()
        process = subprocess.Popen(
            command,
            cwd=SCRAPER_ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        log_lines: list[str] = []
        blocked = False
        assert process.stdout is not None
        for line in process.stdout:
            log_lines.append(line)
            if any(marker in line.casefold() for marker in VERIFY_MARKERS):
                blocked = True
                process.terminate()
                break
        remainder, _ = process.communicate()
        if remainder:
            log_lines.append(remainder)
        log_text = "".join(log_lines)
        log_file.write_text(log_text, encoding="utf-8")
        success = process.returncode == 0 and not blocked
        if success:
            partial_file.replace(output_file)
        append_manifest(
            manifest,
            {
                "icao": icao,
                "slug": slug,
                "started_at": started_at,
                "finished_at": datetime.now().astimezone().isoformat(),
                "status": "success" if success else ("blocked" if blocked else "failed"),
                "return_code": process.returncode,
                "output": str(output_file.relative_to(PROJECT_ROOT)) if success else None,
                "log": str(log_file.relative_to(PROJECT_ROOT)),
            },
        )
        if blocked:
            print(f"STOP: {icao} lieferte Verify/Captcha-Hinweise; Gesamtlauf beendet.")
            return 2
        if not success:
            print(f"WARN: {icao} fehlgeschlagen; Details in {log_file}")

        if index < len(selected):
            pause = randomizer.uniform(args.min_pause, args.max_pause)
            print(f"  Pause: {pause:.0f} Sekunden")
            time.sleep(pause)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
