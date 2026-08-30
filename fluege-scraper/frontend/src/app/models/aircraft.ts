export interface Aircraft {
    code: string;
    type: string | null;
}

export interface AircraftCount {
    aircraft: Aircraft;
    count: number;
}

export interface AirportAircraft {
    aircraft: AircraftCount[];
}
