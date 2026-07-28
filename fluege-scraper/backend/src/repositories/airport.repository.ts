import type { AirportSourceRecord } from '../domain/airport.js';

export interface AirportRepository {
    findAll(): Promise<AirportSourceRecord[]>;
}
