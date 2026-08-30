import type { Airport } from './airport.js';

export interface ConnectionCount {
    connection: Airport;
    count: number;
}

export interface AirportConnections {
    departures: ConnectionCount[];
    arrivals: ConnectionCount[];
}
