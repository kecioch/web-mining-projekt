import express from 'express';

import { errorHandler } from './middleware/error-handler.js';
import { airportRouter } from './routes/airport.routes.js';

export function createApp() {
    const app = express();

    app.disable('x-powered-by');
    app.use(express.json());

    app.get('/api/health', (_request, response) => {
        response.status(200).json({ status: 'ok' });
    });

    // Ab hier die Routen für die verschiedenen Endpunkte

    app.use('/api/airports', airportRouter);

    app.use(errorHandler);

    return app;
}
