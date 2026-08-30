import type { AirportAirlines } from '../domain/airline.js';
import type { AirlineRepository } from '../repositories/airline.repository.js';
import { SupabaseAirlineRepository } from '../repositories/supabase-airline.repository.js';
import type { ConnectionRange } from './connection.service.js';

const RANGE_MS: Record<Exclude<ConnectionRange, 'all'>, number> = {
    '24h': 24 * 60 * 60 * 1000,
    '7d': 7 * 24 * 60 * 60 * 1000,
    '30d': 30 * 24 * 60 * 60 * 1000,
};

export class AirlineService {
    constructor(
        private readonly airlineRepository: AirlineRepository = new SupabaseAirlineRepository(),
    ) {}

    public async getAirlines(
        airportIcao: string,
        range: ConnectionRange,
    ): Promise<AirportAirlines> {
        const from = range === 'all' ? null : new Date(Date.now() - RANGE_MS[range]);
        return this.airlineRepository.findAirlines(airportIcao.toUpperCase(), from);
    }
}
