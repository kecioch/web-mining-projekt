import type { AirportAircraft } from '../domain/aircraft.js';
import type { AircraftRepository } from '../repositories/aircraft.repository.js';
import { SupabaseAircraftRepository } from '../repositories/supabase-aircraft.repository.js';
import type { ConnectionRange } from './connection.service.js';

const RANGE_MS: Record<Exclude<ConnectionRange, 'all'>, number> = {
    '24h': 24 * 60 * 60 * 1000,
    '7d': 7 * 24 * 60 * 60 * 1000,
    '30d': 30 * 24 * 60 * 60 * 1000,
};

export class AircraftService {
    constructor(
        private readonly aircraftRepository: AircraftRepository = new SupabaseAircraftRepository(),
    ) {}

    public async getAircraft(
        airportIcao: string,
        range: ConnectionRange,
    ): Promise<AirportAircraft> {
        const from = range === 'all' ? null : new Date(Date.now() - RANGE_MS[range]);
        return this.aircraftRepository.findAircraft(airportIcao.toUpperCase(), from);
    }
}
