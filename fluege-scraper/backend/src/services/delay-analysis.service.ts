import type {
    AirportDelayAnalysis,
    DailyDelayAnalysis,
    DelayAnalysisRow,
    DelayMetric,
} from '../domain/delay-analysis.js';
import type { DelayAnalysisRepository } from '../repositories/delay-analysis.repository.js';
import { SupabaseDelayAnalysisRepository } from '../repositories/supabase-delay-analysis.repository.js';
import type { ConnectionRange } from './connection.service.js';

const DELAY_THRESHOLD_MINUTES = 15;
const RANGE_DAYS: Record<Exclude<ConnectionRange, 'all'>, number> = {
    '24h': 1,
    '7d': 7,
    '30d': 30,
};

interface MetricTotals {
    flightCount: number;
    evaluatedFlightCount: number;
    delayedFlightCount: number;
    cancelledFlightCount: number;
    totalDelayMinutes: number;
}

export class DelayAnalysisService {
    constructor(
        private readonly delayAnalysisRepository: DelayAnalysisRepository = new SupabaseDelayAnalysisRepository(),
    ) {}

    public async getAnalysis(
        airportIcao: string,
        range: ConnectionRange,
    ): Promise<AirportDelayAnalysis> {
        const rows = await this.delayAnalysisRepository.findByAirport(airportIcao.toUpperCase());
        const latestDate = rows.at(-1)?.analysisDate ?? null;
        const fromDate = latestDate ? this.rangeStart(latestDate, range) : null;
        const filteredRows = fromDate ? rows.filter((row) => row.analysisDate >= fromDate) : rows;
        const firstRow = filteredRows[0];
        const lastRow = filteredRows.at(-1);
        const arrivalRows = filteredRows.filter((row) => row.flightDirection === 'ARRIVAL');
        const departureRows = filteredRows.filter((row) => row.flightDirection === 'DEPARTURE');

        return {
            summary: this.toMetric(this.sumRows(filteredRows)),
            arrivalSummary: this.toMetric(this.sumRows(arrivalRows)),
            departureSummary: this.toMetric(this.sumRows(departureRows)),
            daily: this.toDaily(filteredRows),
            period:
                firstRow && lastRow
                    ? {
                          from: firstRow.analysisDate,
                          to: lastRow.analysisDate,
                      }
                    : null,
            delayThresholdMinutes: DELAY_THRESHOLD_MINUTES,
        };
    }

    private rangeStart(latestDate: string, range: ConnectionRange): string | null {
        if (range === 'all') {
            return null;
        }

        const date = new Date(`${latestDate}T00:00:00Z`);
        date.setUTCDate(date.getUTCDate() - (RANGE_DAYS[range] - 1));
        return date.toISOString().slice(0, 10);
    }

    private toDaily(rows: DelayAnalysisRow[]): DailyDelayAnalysis[] {
        const byDate = new Map<string, DailyDelayAnalysis>();

        for (const row of rows) {
            const day = byDate.get(row.analysisDate) ?? {
                date: row.analysisDate,
                arrival: null,
                departure: null,
            };
            const metric = this.toMetric(this.sumRows([row]));

            if (row.flightDirection === 'ARRIVAL') {
                day.arrival = metric;
            } else {
                day.departure = metric;
            }
            byDate.set(row.analysisDate, day);
        }

        return [...byDate.values()];
    }

    private sumRows(rows: DelayAnalysisRow[]): MetricTotals {
        return rows.reduce<MetricTotals>(
            (totals, row) => ({
                flightCount: totals.flightCount + row.flightCount,
                evaluatedFlightCount: totals.evaluatedFlightCount + row.evaluatedFlightCount,
                delayedFlightCount: totals.delayedFlightCount + row.delayedFlightCount,
                cancelledFlightCount: totals.cancelledFlightCount + row.cancelledFlightCount,
                totalDelayMinutes: totals.totalDelayMinutes + row.totalDelayMinutes,
            }),
            {
                flightCount: 0,
                evaluatedFlightCount: 0,
                delayedFlightCount: 0,
                cancelledFlightCount: 0,
                totalDelayMinutes: 0,
            },
        );
    }

    private toMetric(totals: MetricTotals): DelayMetric {
        return {
            flightCount: totals.flightCount,
            evaluatedFlightCount: totals.evaluatedFlightCount,
            delayedFlightCount: totals.delayedFlightCount,
            cancelledFlightCount: totals.cancelledFlightCount,
            coverageRate: this.percentage(totals.evaluatedFlightCount, totals.flightCount),
            delayRate: this.percentage(totals.delayedFlightCount, totals.evaluatedFlightCount),
            averageDelayMinutes:
                totals.evaluatedFlightCount > 0
                    ? this.round(totals.totalDelayMinutes / totals.evaluatedFlightCount)
                    : null,
        };
    }

    private percentage(value: number, total: number): number | null {
        return total > 0 ? this.round((value / total) * 100) : null;
    }

    private round(value: number): number {
        return Math.round(value * 100) / 100;
    }
}
