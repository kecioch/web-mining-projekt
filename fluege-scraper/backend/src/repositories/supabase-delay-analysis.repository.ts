import type { SupabaseClient } from '@supabase/supabase-js';

import type { DelayAnalysisRow, FlightDirection } from '../domain/delay-analysis.js';
import { getSupabaseClient } from '../lib/supabase.js';
import type { DelayAnalysisRepository } from './delay-analysis.repository.js';

interface SupabaseDelayAnalysisRow {
    analysis_date: string;
    flight_direction: FlightDirection;
    flight_count: number;
    evaluated_flight_count: number;
    delayed_flight_count: number;
    cancelled_flight_count: number;
    total_delay_minutes: number;
}

export class SupabaseDelayAnalysisRepository implements DelayAnalysisRepository {
    constructor(private readonly client?: SupabaseClient) {}

    public async findByAirport(
        airportIcao: string,
        from: Date | null,
        delayThresholdMinutes: number,
    ): Promise<DelayAnalysisRow[]> {
        const client = this.client ?? getSupabaseClient();
        const { data, error } = await client.rpc('airport_delay_analysis', {
            p_icao: airportIcao,
            p_from: from ? from.toISOString() : null,
            p_delay_threshold: delayThresholdMinutes,
        });

        if (error) {
            throw new Error(
                `Supabase-RPC "airport_delay_analysis" failed: ${error.message}`,
            );
        }

        return ((data ?? []) as SupabaseDelayAnalysisRow[]).map((row) => ({
            analysisDate: row.analysis_date,
            flightDirection: row.flight_direction,
            flightCount: Number(row.flight_count),
            evaluatedFlightCount: Number(row.evaluated_flight_count),
            delayedFlightCount: Number(row.delayed_flight_count),
            cancelledFlightCount: Number(row.cancelled_flight_count),
            totalDelayMinutes: Number(row.total_delay_minutes),
        }));
    }
}
