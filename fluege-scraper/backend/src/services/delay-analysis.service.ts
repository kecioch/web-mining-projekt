import type {
    AirportDelayAnalysis,
    DailyDelayAnalysis,
    DelayAnalysisRow,
    DelayMetric,
    HourlyDelayAnalysis,
    HourlyDelayAnalysisRow,
} from '../domain/delay-analysis.js';
import type { DelayAnalysisRepository } from '../repositories/delay-analysis.repository.js';
import { SupabaseDelayAnalysisRepository } from '../repositories/supabase-delay-analysis.repository.js';
import { AnalysisPeriodService } from './analysis-period.service.js';
import type { ConnectionRange } from './connection.service.js';

const DELAY_THRESHOLD_MINUTES = 15;

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
        private readonly analysisPeriodService: AnalysisPeriodService = new AnalysisPeriodService(),
    ) {}

    public async getAnalysis(
        airportIcao: string,
        range: ConnectionRange,
    ): Promise<AirportDelayAnalysis> {
        const normalizedIcao = airportIcao.toUpperCase();
        const from = await this.analysisPeriodService.getFromTimestamp(normalizedIcao, range);
        const rows = await this.delayAnalysisRepository.findByAirport(
            normalizedIcao,
            from,
            DELAY_THRESHOLD_MINUTES,
        );
        const firstRow = rows[0];
        const lastRow = rows.at(-1);
        const arrivalRows = rows.filter((row) => row.flightDirection === 'ARRIVAL');
        const departureRows = rows.filter((row) => row.flightDirection === 'DEPARTURE');

        const hourly =
            range === '24h' && from
                ? this.toHourly(
                      await this.delayAnalysisRepository.findHourlyByAirport(
                          normalizedIcao,
                          from,
                          DELAY_THRESHOLD_MINUTES,
                      ),
                  )
                : undefined;

        return {
            summary: this.toMetric(this.sumRows(rows)),
            arrivalSummary: this.toMetric(this.sumRows(arrivalRows)),
            departureSummary: this.toMetric(this.sumRows(departureRows)),
            daily: this.toDaily(rows),
            ...(hourly ? { hourly } : {}),
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

    private toHourly(rows: HourlyDelayAnalysisRow[]): HourlyDelayAnalysis[] {
        const byHour = new Map<string, HourlyDelayAnalysis>();

        for (const row of rows) {
            const bucket = byHour.get(row.bucketStart) ?? {
                hour: row.bucketStart,
                arrival: null,
                departure: null,
            };
            const metric = this.toMetric(this.sumRows([this.hourlyRowToDailyRow(row)]));

            if (row.flightDirection === 'ARRIVAL') {
                bucket.arrival = metric;
            } else {
                bucket.departure = metric;
            }
            byHour.set(row.bucketStart, bucket);
        }

        return [...byHour.values()];
    }

    private hourlyRowToDailyRow(row: HourlyDelayAnalysisRow): DelayAnalysisRow {
        return {
            analysisDate: row.bucketStart,
            flightDirection: row.flightDirection,
            flightCount: row.flightCount,
            evaluatedFlightCount: row.evaluatedFlightCount,
            delayedFlightCount: row.delayedFlightCount,
            cancelledFlightCount: row.cancelledFlightCount,
            totalDelayMinutes: row.totalDelayMinutes,
        };
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
        const onTimeFlightCount = totals.evaluatedFlightCount - totals.delayedFlightCount;

        return {
            flightCount: totals.flightCount,
            evaluatedFlightCount: totals.evaluatedFlightCount,
            onTimeFlightCount,
            delayedFlightCount: totals.delayedFlightCount,
            cancelledFlightCount: totals.cancelledFlightCount,
            coverageRate: this.percentage(totals.evaluatedFlightCount, totals.flightCount),
            onTimeRate: this.percentage(onTimeFlightCount, totals.evaluatedFlightCount),
            delayRate: this.percentage(totals.delayedFlightCount, totals.evaluatedFlightCount),
            cancellationRate: this.percentage(totals.cancelledFlightCount, totals.flightCount),
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
