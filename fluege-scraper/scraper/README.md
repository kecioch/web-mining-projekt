# Scraper

Dieser Ordner enthält die eigenständige Python-/Scrapy-Anwendung des Projekts.
Die erzeugten Dateien werden im gemeinsamen Verzeichnis `../data/output/`
abgelegt und dort vom Backend gelesen.

## Einrichtung

Vom Projekt-Root aus:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r scraper\requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

## Verwendung

Scrapy erwartet seine Konfiguration im Verzeichnis `scraper/`:

```powershell
Set-Location scraper
..\.venv\Scripts\python.exe -m scrapy list
```

Weitere Beispiele stehen in [COMMANDS.md](COMMANDS.md).
