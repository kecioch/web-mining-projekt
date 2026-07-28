import type { NextFunction, Request, Response } from 'express';

import { AirportService } from '../services/airport.service.js';

export class AirportController {
    constructor(private readonly airportService = new AirportService()) {}

    public async getAll(_request: Request, response: Response, next: NextFunction): Promise<void> {
        try {
            const airports = await this.airportService.getAll();
            response.status(200).json(airports);
        } catch (error) {
            next(error);
        }
    }
}
