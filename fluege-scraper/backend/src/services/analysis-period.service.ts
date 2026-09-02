import type { AnalysisPeriodRepository } from '../repositories/analysis-period.repository.js';
import { SupabaseAnalysisPeriodRepository } from '../repositories/supabase-analysis-period.repository.js';
import type { ConnectionRange } from './connection.service.js';

const RANGE_MILLISECONDS: Record<Exclude<ConnectionRange, 'all'>, number> = {
    '24h': 24 * 60 * 60 * 1000,
    '7d': 7 * 24 * 60 * 60 * 1000,
    '30d': 30 * 24 * 60 * 60 * 1000,
};

export class AnalysisPeriodService {
    constructor(
        private readonly analysisPeriodRepository: AnalysisPeriodRepository = new SupabaseAnalysisPeriodRepository(),
    ) {}

    public async getFromTimestamp(
        airportIcao: string,
        range: ConnectionRange,
    ): Promise<Date | null> {
        if (range === 'all') {
            return null;
        }

        const latestMovementAt = await this.analysisPeriodRepository.findLatestMovementAt(
            airportIcao.toUpperCase(),
        );
        if (!latestMovementAt) {
            return null;
        }

        return new Date(latestMovementAt.getTime() - RANGE_MILLISECONDS[range]);
    }
}
