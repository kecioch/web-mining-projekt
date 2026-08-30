import type { SupabaseClient } from '@supabase/supabase-js';

import type { Airline, AirlineCount, AirportAirlines } from '../domain/airline.js';
import { getSupabaseClient } from '../lib/supabase.js';
import type { AirlineRepository } from './airline.repository.js';

interface AirlineRow {
    airline_icao: string;
    airline_name: string | null;
    airline_iata: string | null;
    flight_count: number;
}

export class SupabaseAirlineRepository implements AirlineRepository {
    constructor(private readonly client?: SupabaseClient) {}

    public async findAirlines(airportIcao: string, from: Date | null): Promise<AirportAirlines> {
        const client = this.client ?? getSupabaseClient();

        const { data, error } = await client.rpc('airport_airlines', {
            p_icao: airportIcao,
            p_from: from ? from.toISOString() : null,
        });

        if (error) {
            throw new Error(`Supabase-RPC "airport_airlines" failed: ${error.message}`);
        }

        const rows = (data ?? []) as AirlineRow[];
        const airlines: AirlineCount[] = rows.map((row) => ({
            airline: this.toAirline(row),
            count: Number(row.flight_count),
        }));

        airlines.sort((a, b) => b.count - a.count);

        return { airlines };
    }

    private toAirline(row: AirlineRow): Airline {
        return {
            icao: row.airline_icao,
            name: row.airline_name,
            iata: row.airline_iata,
        };
    }
}
