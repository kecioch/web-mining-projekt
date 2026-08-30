import { Component, computed, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SkeletonModule } from 'primeng/skeleton';
import { TableModule } from 'primeng/table';

import { Airline, AirportAirlines } from '../../models/airline';
import { Airport } from '../../models/airport';
import { AirportConnections, ConnectionCount, ConnectionRange } from '../../models/connection';

interface AirportDetailRow {
    label: string;
    value: string;
}

interface RangeOption {
    label: string;
    value: ConnectionRange;
}

interface AirlineSlice {
    key: string;
    label: string;
    percent: number;
    color: string;
    path: string;
    isOther: boolean;
}

const AIRLINE_COLORS = [
    '#2563eb',
    '#f97316',
    '#10b981',
    '#a855f7',
    '#ef4444',
    '#eab308',
];
const AIRLINE_OTHER_COLOR = '#94a3b8';
const AIRLINE_MIN_PERCENT = 5;
const PIE_CENTER = 100;
const PIE_RADIUS_OUTER = 90;
const PIE_RADIUS_INNER = 52;

@Component({
    selector: 'app-airport-details',
    imports: [ButtonModule, FormsModule, SelectButtonModule, SkeletonModule, TableModule],
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
    readonly range = input<ConnectionRange>('7d');
    readonly rangeChange = output<ConnectionRange>();

    protected readonly hoveredAirline = signal<number | null>(null);
    protected readonly showDeparturesList = signal(false);
    protected readonly showArrivalsList = signal(false);

    protected readonly rangeOptions: RangeOption[] = [
        { label: '24 h', value: '24h' },
        { label: '7 Tage', value: '7d' },
        { label: '30 Tage', value: '30d' },
        { label: 'Gesamt', value: 'all' },
    ];

    protected readonly detailRows = computed<AirportDetailRow[]>(() => {
        const airport = this.airport();

        return [
            { label: 'ICAO', value: airport.icao ?? '-' },
            { label: 'IATA', value: airport.iata ?? '-' },
            { label: 'Name', value: airport.name ?? '-' },
        ];
    });

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
    protected readonly arrivalsRest = computed<ConnectionCount[]>(() =>
        this.arrivals().slice(3),
    );

    protected onRangeChange(value: ConnectionRange | null): void {
        if (value) {
            this.rangeChange.emit(value);
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
