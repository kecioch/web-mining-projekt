import { Router } from 'express';

import { AirportController } from '../controllers/airport.controller.js';

const airportController = new AirportController();

export const airportRouter = Router();

airportRouter.get('/', airportController.getAll.bind(airportController));
