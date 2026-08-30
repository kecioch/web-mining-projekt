import type { SupabaseClient } from '@supabase/supabase-js';

import type { Airport } from '../domain/airport.js';
import type { AirportConnections, ConnectionCount } from '../domain/connection.js';
import { getSupabaseClient } from '../lib/supabase.js';
import type { ConnectionRepository } from './connection.repository.js';

interface ConnectionRow {
    direction: 'departure' | 'arrival';
    connection_icao: string;
    connection_name: string | null;
    connection_iata: string | null;
    connection_latitude: number | null;
    connection_longitude: number | null;
    connection_website_url: string | null;
    flight_count: number;
}

export class SupabaseConnectionRepository implements ConnectionRepository {
    constructor(private readonly client?: SupabaseClient) {}

    public async findConnections(
        airportIcao: string,
        from: Date | null,
    ): Promise<AirportConnections> {
        const client = this.client ?? getSupabaseClient();

        const { data, error } = await client.rpc('airport_connections', {
            p_icao: airportIcao,
            p_from: from ? from.toISOString() : null,
        });

        if (error) {
            throw new Error(`Supabase-RPC "airport_connections" failed: ${error.message}`);
        }

        const rows = (data ?? []) as ConnectionRow[];
        const departures: ConnectionCount[] = [];
        const arrivals: ConnectionCount[] = [];

        for (const row of rows) {
            const item: ConnectionCount = {
                connection: this.toAirport(row),
                count: Number(row.flight_count),
            };

            if (row.direction === 'departure') {
                departures.push(item);
            } else {
                arrivals.push(item);
            }
        }

        const byCountDesc = (a: ConnectionCount, b: ConnectionCount): number => b.count - a.count;
        departures.sort(byCountDesc);
        arrivals.sort(byCountDesc);

        return { departures, arrivals };
    }

    private toAirport(row: ConnectionRow): Airport {
        return {
            icao: row.connection_icao,
            name: row.connection_name,
            iata: row.connection_iata,
            latitude: row.connection_latitude,
            longitude: row.connection_longitude,
            website_url: row.connection_website_url,
        };
    }
}
