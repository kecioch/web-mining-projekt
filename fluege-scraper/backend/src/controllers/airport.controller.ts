import type { NextFunction, Request, Response } from 'express';

import { AircraftService } from '../services/aircraft.service.js';
import { AirlineService } from '../services/airline.service.js';
import { AirportService } from '../services/airport.service.js';
import { ConnectionService, isConnectionRange } from '../services/connection.service.js';
import { DelayAnalysisService } from '../services/delay-analysis.service.js';

export class AirportController {
    constructor(
        private readonly airportService = new AirportService(),
        private readonly connectionService = new ConnectionService(),
        private readonly airlineService = new AirlineService(),
        private readonly aircraftService = new AircraftService(),
        private readonly delayAnalysisService = new DelayAnalysisService(),
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

    public async getAirlines(
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

            const airlines = await this.airlineService.getAirlines(icao, range);
            response.status(200).json(airlines);
        } catch (error) {
            next(error);
        }
    }

    public async getAircraft(
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

            const aircraft = await this.aircraftService.getAircraft(icao, range);
            response.status(200).json(aircraft);
        } catch (error) {
            next(error);
        }
    }

    public async getDelayAnalysis(
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
            const analysis = await this.delayAnalysisService.getAnalysis(icao, range);
            response.status(200).json(analysis);
        } catch (error) {
            next(error);
        }
    }
}
