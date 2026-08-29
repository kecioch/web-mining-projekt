import type { SupabaseClient } from '@supabase/supabase-js';

import { getSupabaseClient } from '../lib/supabase.js';
import { AirportRepository } from './airport.repository.js';
import { AirportSourceRecord } from '../domain/airport.js';

export class SupabaseAirportRepository implements AirportRepository {
    constructor(private readonly client?: SupabaseClient) {}

    public async findAll(): Promise<AirportSourceRecord[]> {
        const client = this.client ?? getSupabaseClient();

        const { data, error } = await client
            .from('airports')
            .select('icao, name, iata, latitude, longitude, website_url')
            .order('icao', { ascending: true });

        if (error) {
            throw new Error(`Supabase-Request of table "airports" failed: ${error.message}`);
        }

        return data ?? ([] as AirportSourceRecord[]);
    }

    public async findTracked(): Promise<AirportSourceRecord[]> {
        const client = this.client ?? getSupabaseClient();

        const { data, error } = await client
            .from('tracked_airports')
            .select('icao, name, iata, latitude, longitude, website_url')
            .order('icao', { ascending: true });

        if (error) {
            throw new Error(`Supabase-Request of view "tracked_airports" failed: ${error.message}`);
        }

        return data ?? ([] as AirportSourceRecord[]);
    }
}
