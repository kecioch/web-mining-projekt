# Express-Backend

Das Backend stellt die vom Scraper erzeugten Daten über eine REST-API bereit.

## Entwicklung

```powershell
npm install
npm run dev
```

Standardmäßig läuft der Server unter `http://localhost:3000`.

## Endpunkte

- `GET /api/health`
- `GET /api/airports`

Die Flughafendaten werden aktuell aus
`data/output/airports_wikipedia_details.json` gelesen. Die Datei enthält ein
JSON-Array. Über die optionale Umgebungsvariable `AIRPORT_DATA_FILE` kann eine
andere Datei angegeben werden.

## Schichten

- `controllers`: HTTP-Anfragen und HTTP-Antworten
- `services`: Geschäftslogik und API-Datenformat
- `repositories`: Datenzugriff; aktuell JSON, später PostgreSQL
- `domain`: gemeinsame fachliche Typen
- `routes`: Zuordnung von URLs und Controllern
