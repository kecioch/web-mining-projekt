import { Component, computed, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TableModule } from 'primeng/table';

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

@Component({
    selector: 'app-airport-details',
    imports: [ButtonModule, FormsModule, SelectButtonModule, TableModule],
    templateUrl: './airport-details.component.html',
    styleUrl: './airport-details.component.scss',
})
export class AirportDetailsComponent {
    readonly airport = input.required<Airport>();
    readonly connections = input<AirportConnections | null>(null);
    readonly loadingConnections = input(false);
    readonly connectionsError = input<string | null>(null);
    readonly range = input<ConnectionRange>('7d');
    readonly rangeChange = output<ConnectionRange>();

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
}
