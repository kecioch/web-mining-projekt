import type { DelayAnalysisRow } from '../domain/delay-analysis.js';

export interface DelayAnalysisRepository {
    findByAirport(airportIcao: string): Promise<DelayAnalysisRow[]>;
}
