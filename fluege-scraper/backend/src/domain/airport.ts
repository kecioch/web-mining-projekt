export interface Airport {
    icao: string;
    name: string | null;
    iata: string | null;
    latitude: number | null;
    longitude: number | null;
    website_url: string | null;

    // OLD JSON AIRPORT PROPERTIES
    // rank: number | null;
    // airport_name: string | null;
    // passengers: number | null;
    // freight_tons: number | null;
    // aircraft_movements: number | null;
    // area_ha: number | null;
    // iata_code: string | null;
    // icao_code: string | null;
    // runways: number | null;
    // elevation: string | null;
    // opened: string | null;
    // airport_url: string;
    // detail_airport_name: string | null;
    // location: string | null;
    // operator: string | null;
    // detail_elevation: string | null;
    // detail_opened: string | null;
    // detail_area: string | null;
    // terminals: string | null;
    // detail_scrape_status: string | null;
    // source_url: string | null;
}

export type AirportSourceRecord = Airport & Record<string, unknown>;
