import type { AirportAirlines } from '../domain/airline.js';
import type { AirlineRepository } from '../repositories/airline.repository.js';
import { SupabaseAirlineRepository } from '../repositories/supabase-airline.repository.js';
import { AnalysisPeriodService } from './analysis-period.service.js';
import type { ConnectionRange } from './connection.service.js';

export class AirlineService {
    constructor(
        private readonly airlineRepository: AirlineRepository = new SupabaseAirlineRepository(),
        private readonly analysisPeriodService: AnalysisPeriodService = new AnalysisPeriodService(),
    ) {}

    public async getAirlines(
        airportIcao: string,
        range: ConnectionRange,
    ): Promise<AirportAirlines> {
        const normalizedIcao = airportIcao.toUpperCase();
        const from = await this.analysisPeriodService.getFromTimestamp(normalizedIcao, range);
        return this.airlineRepository.findAirlines(normalizedIcao, from);
    }
}
