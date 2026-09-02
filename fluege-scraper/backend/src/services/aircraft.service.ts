import type { AirportAircraft } from '../domain/aircraft.js';
import type { AircraftRepository } from '../repositories/aircraft.repository.js';
import { SupabaseAircraftRepository } from '../repositories/supabase-aircraft.repository.js';
import { AnalysisPeriodService } from './analysis-period.service.js';
import type { ConnectionRange } from './connection.service.js';

export class AircraftService {
    constructor(
        private readonly aircraftRepository: AircraftRepository = new SupabaseAircraftRepository(),
        private readonly analysisPeriodService: AnalysisPeriodService = new AnalysisPeriodService(),
    ) {}

    public async getAircraft(
        airportIcao: string,
        range: ConnectionRange,
    ): Promise<AirportAircraft> {
        const normalizedIcao = airportIcao.toUpperCase();
        const from = await this.analysisPeriodService.getFromTimestamp(normalizedIcao, range);
        return this.aircraftRepository.findAircraft(normalizedIcao, from);
    }
}
