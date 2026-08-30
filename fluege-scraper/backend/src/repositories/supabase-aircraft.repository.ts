import type { SupabaseClient } from '@supabase/supabase-js';

import type { Aircraft, AircraftCount, AirportAircraft } from '../domain/aircraft.js';
import { getSupabaseClient } from '../lib/supabase.js';
import type { AircraftRepository } from './aircraft.repository.js';

interface AircraftRow {
    aircraft_code: string;
    aircraft_type: string | null;
    flight_count: number;
}

export class SupabaseAircraftRepository implements AircraftRepository {
    constructor(private readonly client?: SupabaseClient) {}

    public async findAircraft(airportIcao: string, from: Date | null): Promise<AirportAircraft> {
        const client = this.client ?? getSupabaseClient();

        const { data, error } = await client.rpc('airport_aircraft', {
            p_icao: airportIcao,
            p_from: from ? from.toISOString() : null,
        });

        if (error) {
            throw new Error(`Supabase-RPC "airport_aircraft" failed: ${error.message}`);
        }

        const rows = (data ?? []) as AircraftRow[];
        const aircraft: AircraftCount[] = rows.map((row) => ({
            aircraft: this.toAircraft(row),
            count: Number(row.flight_count),
        }));

        aircraft.sort((a, b) => b.count - a.count);

        return { aircraft };
    }

    private toAircraft(row: AircraftRow): Aircraft {
        return {
            code: row.aircraft_code,
            type: row.aircraft_type,
        };
    }
}
