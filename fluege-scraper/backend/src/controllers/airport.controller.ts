import type { NextFunction, Request, Response } from 'express';

import { AirportService } from '../services/airport.service.js';
import { ConnectionService, isConnectionRange } from '../services/connection.service.js';

export class AirportController {
    constructor(
        private readonly airportService = new AirportService(),
        private readonly connectionService = new ConnectionService(),
    ) {}

    public async getAll(_request: Request, response: Response, next: NextFunction): Promise<void> {
        try {
            const airports = await this.airportService.getAll();
            response.status(200).json(airports);
        } catch (error) {
            next(error);
        }
    }

    public async getTracked(
        _request: Request,
        response: Response,
        next: NextFunction,
    ): Promise<void> {
        try {
            const airports = await this.airportService.getTracked();
            response.status(200).json(airports);
        } catch (error) {
            next(error);
        }
    }

    public async getConnections(
        request: Request,
        response: Response,
        next: NextFunction,
    ): Promise<void> {
        try {
            const rawIcao = request.params['icao'];
            const icao = Array.isArray(rawIcao) ? rawIcao[0] : rawIcao;

            if (!icao) {
                response.status(400).json({ message: 'icao ist erforderlich.' });
                return;
            }

            const rangeParam = request.query['range'];
            const range = isConnectionRange(rangeParam) ? rangeParam : '7d';

            const connections = await this.connectionService.getConnections(icao, range);
            response.status(200).json(connections);
        } catch (error) {
            next(error);
        }
    }
}
