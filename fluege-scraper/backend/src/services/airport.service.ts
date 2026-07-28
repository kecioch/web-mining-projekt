import type { Airport, AirportSourceRecord } from '../domain/airport.js';
import { JsonAirportRepository } from '../repositories/json-airport.repository.js';
import type { AirportRepository } from '../repositories/airport.repository.js';

export class AirportService {
    constructor(
        private readonly airportRepository: AirportRepository = new JsonAirportRepository(),
    ) {}

    public async getAll(): Promise<Airport[]> {
        const airports = await this.airportRepository.findAll();

        return airports
            .map((airport) => this.toAirport(airport))
            .sort((first, second) => first.rank - second.rank);
    }

    private toAirport(source: AirportSourceRecord): Airport {
        return {
            rank: source.rank,
            airport_name: source.airport_name,
            passengers: source.passengers ?? null,
            freight_tons: source.freight_tons ?? null,
            aircraft_movements: source.aircraft_movements ?? null,
            area_ha: source.area_ha ?? null,
            iata_code: source.iata_code ?? null,
            icao_code: source.icao_code ?? null,
            runways: source.runways ?? null,
            elevation: source.elevation ?? null,
            opened: source.opened ?? null,
            airport_url: source.airport_url,
            detail_airport_name: source.detail_airport_name ?? null,
            latitude: source.latitude ?? null,
            longitude: source.longitude ?? null,
            location: source.location ?? null,
            operator: source.operator ?? null,
            detail_elevation: source.detail_elevation ?? null,
            detail_opened: source.detail_opened ?? null,
            detail_area: source.detail_area ?? null,
            terminals: source.terminals ?? null,
            detail_scrape_status: source.detail_scrape_status,
            source_url: source.source_url,
        };
    }
}
