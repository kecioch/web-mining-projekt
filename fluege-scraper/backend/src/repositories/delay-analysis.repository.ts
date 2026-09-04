import type { DelayAnalysisRow, HourlyDelayAnalysisRow } from '../domain/delay-analysis.js';

export interface DelayAnalysisRepository {
    findByAirport(
        airportIcao: string,
        from: Date | null,
        delayThresholdMinutes: number,
    ): Promise<DelayAnalysisRow[]>;

    findHourlyByAirport(
        airportIcao: string,
        from: Date,
        delayThresholdMinutes: number,
    ): Promise<HourlyDelayAnalysisRow[]>;
}
