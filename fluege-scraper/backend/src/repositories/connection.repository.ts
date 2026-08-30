import type { AirportConnections } from '../domain/connection.js';

export interface ConnectionRepository {
    findConnections(airportIcao: string, from: Date | null): Promise<AirportConnections>;
}
