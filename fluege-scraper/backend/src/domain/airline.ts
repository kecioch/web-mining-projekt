export interface Airline {
    icao: string;
    name: string | null;
    iata: string | null;
}

export interface AirlineCount {
    airline: Airline;
    count: number;
}

export interface AirportAirlines {
    airlines: AirlineCount[];
}
