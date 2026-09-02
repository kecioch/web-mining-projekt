import type { AirportConnections } from '../domain/connection.js';
import type { ConnectionRepository } from '../repositories/connection.repository.js';
import { SupabaseConnectionRepository } from '../repositories/supabase-connection.repository.js';
import { AnalysisPeriodService } from './analysis-period.service.js';

export type ConnectionRange = '24h' | '7d' | '30d' | 'all';

export function isConnectionRange(value: unknown): value is ConnectionRange {
    return value === '24h' || value === '7d' || value === '30d' || value === 'all';
}

export class ConnectionService {
    constructor(
        private readonly connectionRepository: ConnectionRepository = new SupabaseConnectionRepository(),
        private readonly analysisPeriodService: AnalysisPeriodService = new AnalysisPeriodService(),
    ) {}

    public async getConnections(
        airportIcao: string,
        range: ConnectionRange,
    ): Promise<AirportConnections> {
        const normalizedIcao = airportIcao.toUpperCase();
        const from = await this.analysisPeriodService.getFromTimestamp(normalizedIcao, range);
        return this.connectionRepository.findConnections(normalizedIcao, from);
    }
}
