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

    public async findByAirport(airportIcao: string): Promise<DelayAnalysisRow[]> {
        const client = this.client ?? getSupabaseClient();
        const { data, error } = await client
            .from('airport_analysis')
            .select(
                'analysis_date, flight_direction, flight_count, evaluated_flight_count, delayed_flight_count, cancelled_flight_count, total_delay_minutes',
            )
            .eq('airport_icao', airportIcao)
            .order('analysis_date', { ascending: true });

        if (error) {
            throw new Error(
                `Supabase-Request of table "airport_analysis" failed: ${error.message}`,
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
