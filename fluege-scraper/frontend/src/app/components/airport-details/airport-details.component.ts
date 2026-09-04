import { Component, computed, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { ChartData, ChartOptions } from 'chart.js';
import { CardModule } from 'primeng/card';
import { ChartModule } from 'primeng/chart';
import { MessageModule } from 'primeng/message';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SkeletonModule } from 'primeng/skeleton';
import { TagModule } from 'primeng/tag';

import { Aircraft, AircraftCount, AirportAircraft } from '../../models/aircraft';
import { Airline, AirportAirlines } from '../../models/airline';
import { Airport } from '../../models/airport';
import { AirportConnections, ConnectionCount, ConnectionRange } from '../../models/connection';
import { AirportDelayAnalysis, DelayMetric } from '../../models/delay-analysis';

interface RangeOption {
    label: string;
    value: ConnectionRange;
}

interface DelaySummaryView {
    key: 'all' | 'arrival' | 'departure';
    label: string;
    metric: DelayMetric;
}

type DelaySummaryKey = DelaySummaryView['key'];

interface AirlineSlice {
    key: string;
    label: string;
    percent: number;
    color: string;
    path: string;
    isOther: boolean;
}

const AIRLINE_COLORS = ['#2563eb', '#f97316', '#10b981', '#a855f7', '#ef4444', '#eab308'];
const AIRLINE_OTHER_COLOR = '#94a3b8';
const AIRLINE_MIN_PERCENT = 5;
const PIE_CENTER = 100;
const PIE_RADIUS_OUTER = 90;
const PIE_RADIUS_INNER = 52;

const AIRCRAFT_TOP_COUNT = 6;
const NUMBER_FORMAT = new Intl.NumberFormat('de-DE');
const DATE_FORMAT = new Intl.DateTimeFormat('de-DE', {
    day: '2-digit',
    month: '2-digit',
    timeZone: 'UTC',
});
const WEEKDAY_FORMAT = new Intl.DateTimeFormat('de-DE', {
    weekday: 'short',
    timeZone: 'UTC',
});
const HOUR_FORMAT = new Intl.DateTimeFormat('de-DE', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
});

interface DelayChartPoint {
    label: string;
    arrival: DelayMetric | null;
    departure: DelayMetric | null;
}

@Component({
    selector: 'app-airport-details',
    imports: [
        CardModule,
        ChartModule,
        FormsModule,
        MessageModule,
        SelectButtonModule,
        SkeletonModule,
        TagModule,
    ],
    templateUrl: './airport-details.component.html',
    styleUrl: './airport-details.component.scss',
})
export class AirportDetailsComponent {
    readonly airport = input.required<Airport>();
    readonly connections = input<AirportConnections | null>(null);
    readonly loadingConnections = input(false);
    readonly connectionsError = input<string | null>(null);
    readonly airlines = input<AirportAirlines | null>(null);
    readonly loadingAirlines = input(false);
    readonly airlinesError = input<string | null>(null);
    readonly aircraft = input<AirportAircraft | null>(null);
    readonly loadingAircraft = input(false);
    readonly aircraftError = input<string | null>(null);
    readonly delayAnalysis = input<AirportDelayAnalysis | null>(null);
    readonly loadingDelayAnalysis = input(false);
    readonly delayAnalysisError = input<string | null>(null);
    readonly range = input<ConnectionRange>('7d');
    readonly rangeChange = output<ConnectionRange>();

    protected readonly hoveredAirline = signal<number | null>(null);
    protected readonly showDeparturesList = signal(false);
    protected readonly showArrivalsList = signal(false);
    protected readonly showAircraftList = signal(false);
    protected readonly selectedDelaySummaryKey = signal<DelaySummaryKey>('all');

    protected readonly delaySummaryOptions: { label: string; value: DelaySummaryKey }[] = [
        { label: 'Gesamt', value: 'all' },
        { label: 'Ankünfte', value: 'arrival' },
        { label: 'Abflüge', value: 'departure' },
    ];

    protected readonly delaySummaries = computed<DelaySummaryView[]>(() => {
        const analysis = this.delayAnalysis();
        if (!analysis) {
            return [];
        }

        return [
            { key: 'all', label: 'Gesamt', metric: analysis.summary },
            {
                key: 'arrival',
                label: 'Ankünfte',
                metric: analysis.arrivalSummary ?? this.aggregateDirection(analysis, 'arrival'),
            },
            {
                key: 'departure',
                label: 'Abflüge',
                metric: analysis.departureSummary ?? this.aggregateDirection(analysis, 'departure'),
            },
        ];
    });
    protected readonly selectedDelaySummary = computed<DelaySummaryView | null>(
        () =>
            this.delaySummaries().find(
                (summary) => summary.key === this.selectedDelaySummaryKey(),
            ) ?? null,
    );
    protected readonly delayPeriod = computed(() => {
        const period = this.delayAnalysis()?.period;
        if (!period) {
            return null;
        }
        return `${this.formatDate(period.from)} – ${this.formatDate(period.to)}`;
    });
    protected readonly isHourly = computed<boolean>(
        () => (this.delayAnalysis()?.hourly?.length ?? 0) > 0,
    );
    protected readonly chartPeriodLabel = computed<string>(() =>
        this.isHourly() ? 'pro Stunde' : 'pro Tag',
    );
    private readonly chartPoints = computed<DelayChartPoint[]>(() => {
        const analysis = this.delayAnalysis();
        if (!analysis) {
            return [];
        }

        const hourly = analysis.hourly;
        if (hourly && hourly.length > 0) {
            return hourly.map((bucket) => ({
                label: this.formatChartHour(bucket.hour),
                arrival: bucket.arrival,
                departure: bucket.departure,
            }));
        }

        return analysis.daily.map((day) => ({
            label: this.formatChartDate(day.date),
            arrival: day.arrival,
            departure: day.departure,
        }));
    });
    protected readonly delayRateChart = computed<ChartData<'line'>>(() =>
        this.createChartData((metric) => metric.delayRate),
    );
    protected readonly averageDelayChart = computed<ChartData<'line'>>(() =>
        this.createChartData((metric) => metric.averageDelayMinutes),
    );
    protected readonly delayRateChartOptions = this.createChartOptions(
        '%',
        100,
        (metric) =>
            `${this.formatNumber(metric.delayedFlightCount)}/${this.formatNumber(
                metric.evaluatedFlightCount,
            )}`,
    );
    protected readonly averageDelayChartOptions = this.createChartOptions(
        'min',
        undefined,
        (metric) => `${this.formatNumber(metric.evaluatedFlightCount)}`,
    );

    protected readonly rangeOptions: RangeOption[] = [
        { label: '24 h', value: '24h' },
        { label: '7 Tage', value: '7d' },
        { label: '30 Tage', value: '30d' },
        { label: 'Gesamt', value: 'all' },
    ];

    protected readonly departures = computed<ConnectionCount[]>(
        () => this.connections()?.departures ?? [],
    );
    protected readonly arrivals = computed<ConnectionCount[]>(
        () => this.connections()?.arrivals ?? [],
    );
    protected readonly departuresTop3 = computed<ConnectionCount[]>(() =>
        this.departures().slice(0, 3),
    );
    protected readonly arrivalsTop3 = computed<ConnectionCount[]>(() =>
        this.arrivals().slice(0, 3),
    );
    protected readonly departuresRest = computed<ConnectionCount[]>(() =>
        this.departures().slice(3),
    );
    protected readonly arrivalsRest = computed<ConnectionCount[]>(() => this.arrivals().slice(3));

    protected onRangeChange(value: ConnectionRange | null): void {
        if (value) {
            this.rangeChange.emit(value);
        }
    }

    protected onDelaySummaryChange(value: DelaySummaryKey | null): void {
        if (value) {
            this.selectedDelaySummaryKey.set(value);
        }
    }

    protected connectionLabel(connection: Airport): string {
        const code = connection.iata ?? connection.icao;
        return connection.name ? `${connection.name} (${code})` : code;
    }

    protected barPercent(count: number, top: ConnectionCount[]): number {
        const max = top[0]?.count ?? 0;
        return max > 0 ? Math.round((count / max) * 100) : 0;
    }

    protected readonly airlineSlices = computed<AirlineSlice[]>(() => {
        const list = this.airlines()?.airlines ?? [];
        const total = list.reduce((sum, item) => sum + item.count, 0);
        if (total === 0) {
            return [];
        }

        const threshold = total * (AIRLINE_MIN_PERCENT / 100);
        const visible = list.filter((item) => item.count >= threshold);
        const rest = list.filter((item) => item.count < threshold);

        const segments = visible.map((item, index) => ({
            key: item.airline.icao,
            label: this.airlineLabel(item.airline),
            count: item.count,
            color: AIRLINE_COLORS[index % AIRLINE_COLORS.length],
            isOther: false,
        }));

        if (rest.length > 0) {
            segments.push({
                key: '__other__',
                label: 'Sonstige',
                count: rest.reduce((sum, item) => sum + item.count, 0),
                color: AIRLINE_OTHER_COLOR,
                isOther: true,
            });
        }

        const slices: AirlineSlice[] = [];
        let startAngle = 0;
        for (const segment of segments) {
            const sweep = (segment.count / total) * 360;
            const endAngle = startAngle + sweep;
            slices.push({
                key: segment.key,
                label: segment.label,
                percent: Math.round((segment.count / total) * 100),
                color: segment.color,
                path: this.donutPath(startAngle, endAngle),
                isOther: segment.isOther,
            });
            startAngle = endAngle;
        }

        return slices;
    });

    protected readonly hoveredAirlineSlice = computed<AirlineSlice | null>(() => {
        const index = this.hoveredAirline();
        if (index === null) {
            return null;
        }
        return this.airlineSlices()[index] ?? null;
    });

    protected onAirlineHover(index: number | null): void {
        this.hoveredAirline.set(index);
    }

    protected toggleDeparturesList(): void {
        this.showDeparturesList.update((value) => !value);
    }

    protected toggleArrivalsList(): void {
        this.showArrivalsList.update((value) => !value);
    }

    protected airlineLabel(airline: Airline): string {
        const code = airline.iata ?? airline.icao;
        return airline.name ? `${airline.name} (${code})` : code;
    }

    protected readonly aircraftList = computed<AircraftCount[]>(
        () => this.aircraft()?.aircraft ?? [],
    );
    protected readonly aircraftTop = computed<AircraftCount[]>(() =>
        this.aircraftList().slice(0, AIRCRAFT_TOP_COUNT),
    );
    protected readonly aircraftRest = computed<AircraftCount[]>(() =>
        this.aircraftList().slice(AIRCRAFT_TOP_COUNT),
    );

    protected toggleAircraftList(): void {
        this.showAircraftList.update((value) => !value);
    }

    protected aircraftLabel(aircraft: Aircraft): string {
        return aircraft.type ? aircraft.type : aircraft.code;
    }

    protected aircraftBarPercent(count: number): number {
        const max = this.aircraftTop()[0]?.count ?? 0;
        return max > 0 ? Math.round((count / max) * 100) : 0;
    }

    protected formatNumber(value: number): string {
        return NUMBER_FORMAT.format(value);
    }

    protected formatPercent(value: number | null): string {
        return value === null ? '–' : `${value.toFixed(1).replace('.', ',')} %`;
    }

    protected formatMinutes(value: number | null): string {
        return value === null ? '–' : `${value.toFixed(1).replace('.', ',')} min`;
    }

    private aggregateDirection(
        analysis: AirportDelayAnalysis,
        direction: 'arrival' | 'departure',
    ): DelayMetric {
        const metrics = analysis.daily.flatMap((day) => (day[direction] ? [day[direction]] : []));
        const flightCount = metrics.reduce((sum, metric) => sum + metric.flightCount, 0);
        const evaluatedFlightCount = metrics.reduce(
            (sum, metric) => sum + metric.evaluatedFlightCount,
            0,
        );
        const onTimeFlightCount = metrics.reduce(
            (sum, metric) => sum + metric.onTimeFlightCount,
            0,
        );
        const delayedFlightCount = metrics.reduce(
            (sum, metric) => sum + metric.delayedFlightCount,
            0,
        );
        const cancelledFlightCount = metrics.reduce(
            (sum, metric) => sum + metric.cancelledFlightCount,
            0,
        );
        const totalDelayMinutes = metrics.reduce(
            (sum, metric) => sum + (metric.averageDelayMinutes ?? 0) * metric.evaluatedFlightCount,
            0,
        );

        return {
            flightCount,
            evaluatedFlightCount,
            onTimeFlightCount,
            delayedFlightCount,
            cancelledFlightCount,
            coverageRate: this.percentage(evaluatedFlightCount, flightCount),
            onTimeRate: this.percentage(onTimeFlightCount, evaluatedFlightCount),
            delayRate: this.percentage(delayedFlightCount, evaluatedFlightCount),
            cancellationRate: this.percentage(cancelledFlightCount, flightCount),
            averageDelayMinutes:
                evaluatedFlightCount > 0 ? totalDelayMinutes / evaluatedFlightCount : null,
        };
    }

    private percentage(value: number, total: number): number | null {
        return total > 0 ? (value / total) * 100 : null;
    }

    private createChartData(getter: (metric: DelayMetric) => number | null): ChartData<'line'> {
        const points = this.chartPoints();
        return {
            labels: points.map((point) => point.label),
            datasets: [
                {
                    label: 'Ankunft',
                    data: points.map((point) => (point.arrival ? getter(point.arrival) : null)),
                    borderColor: '#3b82f6',
                    backgroundColor: '#3b82f6',
                    tension: 0.3,
                    spanGaps: true,
                },
                {
                    label: 'Abflug',
                    data: points.map((point) =>
                        point.departure ? getter(point.departure) : null,
                    ),
                    borderColor: '#f97316',
                    backgroundColor: '#f97316',
                    tension: 0.3,
                    spanGaps: true,
                },
            ],
        };
    }

    private createChartOptions(
        unit: '%' | 'min',
        max?: number,
        countLabel?: (metric: DelayMetric) => string,
    ): ChartOptions<'line'> {
        return {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            plugins: {
                legend: {
                    labels: { usePointStyle: true, boxWidth: 8, boxHeight: 8 },
                },
                tooltip: {
                    callbacks: {
                        label: (context) => {
                            const base = `${context.dataset.label}: ${this.formatChartValue(context.parsed.y, unit)}`;
                            if (!countLabel || !this.isHourly()) {
                                return base;
                            }

                            const point = this.chartPoints()[context.dataIndex];
                            const metric =
                                context.datasetIndex === 0
                                    ? point?.arrival
                                    : point?.departure;
                            return metric ? `${base} (${countLabel(metric)})` : base;
                        },
                    },
                },
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { autoSkip: true, maxTicksLimit: 5, maxRotation: 0 },
                },
                y: {
                    beginAtZero: true,
                    max,
                    ticks: {
                        callback: (value) => `${value} ${unit}`,
                    },
                },
            },
        };
    }

    private formatDate(value: string): string {
        if (!value) {
            return '';
        }
        return DATE_FORMAT.format(new Date(`${value}T00:00:00Z`));
    }

    private formatChartDate(value: string): string {
        if (!value) {
            return '';
        }

        const date = new Date(`${value}T00:00:00Z`);
        const weekday = WEEKDAY_FORMAT.format(date).replace(/\.$/, '');
        return `${DATE_FORMAT.format(date)} (${weekday})`;
    }

    private formatChartHour(value: string): string {
        if (!value) {
            return '';
        }

        // Der Backend-Zeitstempel ist bereits Berliner Ortszeit (ohne Zeitzone),
        // daher wird er als UTC interpretiert, um die Stunde unverändert anzuzeigen.
        const normalized = value.includes('T') ? value : value.replace(' ', 'T');
        const date = new Date(`${normalized}Z`);
        return `${HOUR_FORMAT.format(date)} Uhr`;
    }

    private formatChartValue(value: number | null, unit: '%' | 'min'): string {
        if (value === null) {
            return '–';
        }

        return `${value.toFixed(1).replace('.', ',')} ${unit}`;
    }

    private donutPath(startAngle: number, endAngle: number): string {
        if (endAngle - startAngle > 359.999) {
            const mid = startAngle + 180;
            return `${this.donutSegment(startAngle, mid)} ${this.donutSegment(mid, endAngle)}`;
        }
        return this.donutSegment(startAngle, endAngle);
    }

    private donutSegment(startAngle: number, endAngle: number): string {
        const outerStart = this.polar(PIE_RADIUS_OUTER, startAngle);
        const outerEnd = this.polar(PIE_RADIUS_OUTER, endAngle);
        const innerEnd = this.polar(PIE_RADIUS_INNER, endAngle);
        const innerStart = this.polar(PIE_RADIUS_INNER, startAngle);
        const largeArc = endAngle - startAngle > 180 ? 1 : 0;

        return [
            `M ${outerStart.x} ${outerStart.y}`,
            `A ${PIE_RADIUS_OUTER} ${PIE_RADIUS_OUTER} 0 ${largeArc} 1 ${outerEnd.x} ${outerEnd.y}`,
            `L ${innerEnd.x} ${innerEnd.y}`,
            `A ${PIE_RADIUS_INNER} ${PIE_RADIUS_INNER} 0 ${largeArc} 0 ${innerStart.x} ${innerStart.y}`,
            'Z',
        ].join(' ');
    }

    private polar(radius: number, angleDeg: number): { x: number; y: number } {
        const angle = ((angleDeg - 90) * Math.PI) / 180;
        return {
            x: Number((PIE_CENTER + radius * Math.cos(angle)).toFixed(2)),
            y: Number((PIE_CENTER + radius * Math.sin(angle)).toFixed(2)),
        };
    }
}
