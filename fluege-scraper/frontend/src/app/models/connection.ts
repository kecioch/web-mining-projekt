import { Airport } from './airport';

export type ConnectionRange = '24h' | '7d' | '30d' | 'all';

export interface ConnectionCount {
    connection: Airport;
    count: number;
}

export interface AirportConnections {
    departures: ConnectionCount[];
    arrivals: ConnectionCount[];
}
