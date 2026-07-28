import type { ErrorRequestHandler } from 'express';

export const errorHandler: ErrorRequestHandler = (error, _request, response, _next) => {
    console.error(error);
    response.status(500).json({
        error: 'Die Flughafendaten konnten nicht geladen werden.',
    });
};
