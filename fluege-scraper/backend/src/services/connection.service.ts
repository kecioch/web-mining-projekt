import type { AirportConnections } from '../domain/connection.js';
import type { ConnectionRepository } from '../repositories/connection.repository.js';
import { SupabaseConnectionRepository } from '../repositories/supabase-connection.repository.js';

export type ConnectionRange = '24h' | '7d' | '30d' | 'all';

const RANGE_MS: Record<Exclude<ConnectionRange, 'all'>, number> = {
    '24h': 24 * 60 * 60 * 1000,
    '7d': 7 * 24 * 60 * 60 * 1000,
    '30d': 30 * 24 * 60 * 60 * 1000,
};

export function isConnectionRange(value: unknown): value is ConnectionRange {
    return value === '24h' || value === '7d' || value === '30d' || value === 'all';
}

export class ConnectionService {
    constructor(
        private readonly connectionRepository: ConnectionRepository = new SupabaseConnectionRepository(),
    ) {}

    public async getConnections(
        airportIcao: string,
        range: ConnectionRange,
    ): Promise<AirportConnections> {
        const from = range === 'all' ? null : new Date(Date.now() - RANGE_MS[range]);
        return this.connectionRepository.findConnections(airportIcao.toUpperCase(), from);
    }
}
