# Scrapy-Befehle

Die Befehle werden aus dem Verzeichnis `scraper/` ausgeführt:

## Wikipedia-Stammdaten

```powershell
..\.venv\Scripts\python.exe -m scrapy crawl airports_wikipedia `
  -O ..\data\output\airports_wikipedia_details.json

..\.venv\Scripts\python.exe -m scrapy crawl airlines_wikipedia `
  -O ..\data\output\airlines_wikipedia_details.json
```

## Aktuelle Abflüge aus Frankfurt

```powershell
..\.venv\Scripts\python.exe -m scrapy crawl flightera_flights `
  -a airport_icao=EDDF `
  -a airport_slug=Frankfurt `
  -a movement_type=departure `
  -O ..\data\output\flights.json
```

## Zeitlich definierte Abflüge aus Frankfurt

```powershell
..\.venv\Scripts\python.exe -m scrapy crawl flightera_flights `
  -a airport_icao=EDDF `
  -a airport_slug=Frankfurt `
  -a movement_type=departure `
  -a start_date=2026-07-01 `
  -a start_time=00:00 `
  -a end_date=2026-07-01 `
  -a end_time=23:59 `
  -O ..\data\output\flights-2026-07-01.json
```

## Begrenzter Testlauf

```powershell
..\.venv\Scripts\python.exe -m scrapy crawl flightera_flights `
  -a airport_icao=EDDF `
  -a airport_slug=Frankfurt `
  -a movement_type=departure `
  -a start_date=2026-07-01 `
  -a start_time=12:00 `
  -a end_date=2026-07-01 `
  -a end_time=12:15 `
  -s DOWNLOAD_DELAY=5 `
  -s RANDOMIZE_DOWNLOAD_DELAY=True `
  -O ..\data\output\EDDF_2026-TEST1.json
```

## Mehrere Flughäfen delegieren

```powershell
..\.venv\Scripts\python.exe delegate_flightera.py --max-airports 5
```

## Frankfurt Airport (JSON)

```powershell
..\.venv\Scripts\python.exe -m scrapy crawl frankfurt_airport_flights `
  -a movement_type=departure `
  -a service_date=2026-08-27 `
  -a start_time=12:00 `
  -a end_time=23:59 `
  -a max_pages=50 `
  -a per_page=50 `
  -O ..\data\output\EDDF_2026-08-27_dep.json
```

## Munich Airport (HTML)

```powershell
..\.venv\Scripts\python.exe -m scrapy crawl munich_airport_flights `
  -a movement_type=departure `
  -a service_date=2026-08-27 `
  -a max_pages=50 `
  -a per_page=50 `
  -O ..\data\output\EDDM_2026-08-27_dep.json
```

## Berlin Brandenburg Airport (JSON)

```powershell
..\.venv\Scripts\python.exe -m scrapy crawl berlin_airport_flights `
  -a movement_type=arrival `
  -a service_date=2026-08-27 `
  -a start_time=10:00 `
  -a end_time=23:59 `
  -a max_pages=50 `
  -a per_page=50 `
  -O ..\data\output\EDDB_2026-08-27_arr.json