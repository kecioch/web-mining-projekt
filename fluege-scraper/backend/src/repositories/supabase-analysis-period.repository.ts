import type { SupabaseClient } from '@supabase/supabase-js';

import { getSupabaseClient } from '../lib/supabase.js';
import type { AnalysisPeriodRepository } from './analysis-period.repository.js';

export class SupabaseAnalysisPeriodRepository implements AnalysisPeriodRepository {
    constructor(private readonly client?: SupabaseClient) {}

    public async findLatestMovementAt(airportIcao: string): Promise<Date | null> {
        const client = this.client ?? getSupabaseClient();
        const { data, error } = await client.rpc('airport_latest_movement_at', {
            p_icao: airportIcao,
        });

        if (error) {
            throw new Error(
                `Supabase-RPC "airport_latest_movement_at" failed: ${error.message}`,
            );
        }

        if (typeof data !== 'string') {
            return null;
        }

        const latestMovementAt = new Date(data);
        if (Number.isNaN(latestMovementAt.getTime())) {
            throw new Error(
                `Supabase-RPC "airport_latest_movement_at" returned an invalid timestamp: ${data}`,
            );
        }

        return latestMovementAt;
    }
}
