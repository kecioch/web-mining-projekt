import type { DelayAnalysisRow } from '../domain/delay-analysis.js';

export interface DelayAnalysisRepository {
    findByAirport(
        airportIcao: string,
        from: Date | null,
        delayThresholdMinutes: number,
    ): Promise<DelayAnalysisRow[]>;
}
