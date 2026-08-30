import type { AirportAircraft } from '../domain/aircraft.js';

export interface AircraftRepository {
    findAircraft(airportIcao: string, from: Date | null): Promise<AirportAircraft>;
}
