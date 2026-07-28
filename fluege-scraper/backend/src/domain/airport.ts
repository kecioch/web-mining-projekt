export interface Airport {
    rank: number;
    airport_name: string;
    passengers: number | null;
    freight_tons: number | null;
    aircraft_movements: number | null;
    area_ha: number | null;
    iata_code: string | null;
    icao_code: string | null;
    runways: number | null;
    elevation: string | null;
    opened: string | null;
    airport_url: string;
    detail_airport_name: string | null;
    latitude: number | null;
    longitude: number | null;
    location: string | null;
    operator: string | null;
    detail_elevation: string | null;
    detail_opened: string | null;
    detail_area: string | null;
    terminals: string | null;
    detail_scrape_status: string;
    source_url: string;
}

export type AirportSourceRecord = Airport & Record<string, unknown>;
