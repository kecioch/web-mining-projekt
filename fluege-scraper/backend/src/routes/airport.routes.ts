import { Router } from 'express';

import { AirportController } from '../controllers/airport.controller.js';

const airportController = new AirportController();

export const airportRouter = Router();

airportRouter.get('/', airportController.getAll.bind(airportController));
airportRouter.get('/tracked', airportController.getTracked.bind(airportController));
airportRouter.get('/:icao/connections', airportController.getConnections.bind(airportController));
airportRouter.get('/:icao/airlines', airportController.getAirlines.bind(airportController));
