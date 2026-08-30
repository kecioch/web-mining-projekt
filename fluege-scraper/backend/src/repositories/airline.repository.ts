import type { AirportAirlines } from '../domain/airline.js';

export interface AirlineRepository {
    findAirlines(airportIcao: string, from: Date | null): Promise<AirportAirlines>;
}
