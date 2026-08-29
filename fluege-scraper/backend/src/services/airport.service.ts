import type { Airport, AirportSourceRecord } from '../domain/airport.js';
import { CachedAirportRepository } from '../repositories/cached-airport.repository.js';
import { SupabaseAirportRepository } from '../repositories/supabase-airport.repository.js';
import type { AirportRepository } from '../repositories/airport.repository.js';

export class AirportService {
    constructor(
        private readonly airportRepositorySupabase: AirportRepository = new CachedAirportRepository(
            new SupabaseAirportRepository(),
        ),
    ) {}

    public async getAll(): Promise<Airport[]> {
        return this.airportRepositorySupabase.findAll();
    }

    public async getTracked(): Promise<Airport[]> {
        return await this.airportRepositorySupabase.findTracked();
    }

    private toAirport(source: AirportSourceRecord): Airport {
        return {
            icao: source.icao,
            name: source.name,
            iata: source.iata,
            latitude: source.latitude,
            longitude: source.longitude,
            website_url: source.website_url,
        };
    }
}
