import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import type { AirportSourceRecord } from '../domain/airport.js';
import type { AirportRepository } from './airport.repository.js';

export class JsonAirportRepository implements AirportRepository {
    constructor(
        private readonly filePath = process.env['AIRPORT_DATA_FILE'] ??
            path.resolve(
                path.dirname(fileURLToPath(import.meta.url)),
                '../../../data/output/airports_wikipedia_details.json',
            ),
    ) {}
    
    findTracked(): Promise<AirportSourceRecord[]> {
        throw new Error('Method not implemented.');
    }

    public async findAll(): Promise<AirportSourceRecord[]> {
        const content = await readFile(this.filePath, 'utf8');

        const airports: unknown = JSON.parse(content);

        if (!Array.isArray(airports)) {
            throw new TypeError(`Airport-Datei muss ein JSON-Array enthalten: ${this.filePath}`);
        }

        return airports as AirportSourceRecord[];
    }
}
