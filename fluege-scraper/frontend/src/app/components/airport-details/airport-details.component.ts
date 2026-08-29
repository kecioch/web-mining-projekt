import { Component, computed, input } from '@angular/core';
import { ButtonModule } from 'primeng/button';
import { TableModule } from 'primeng/table';

import { Airport } from '../../models/airport';

interface AirportDetailRow {
    label: string;
    value: string;
}

@Component({
    selector: 'app-airport-details',
    imports: [ButtonModule, TableModule],
    templateUrl: './airport-details.component.html',
    styleUrl: './airport-details.component.scss',
})
export class AirportDetailsComponent {
    readonly airport = input.required<Airport>();

    protected readonly detailRows = computed<AirportDetailRow[]>(() => {
        const airport = this.airport();

        return [
            { label: 'ICAO', value: airport.icao ?? '-' },
            { label: 'IATA', value: airport.iata ?? '-' },
            { label: 'Name', value: airport.name ?? '-' },
            
        ];
    });

    private formatNumber(value: number | null, suffix = ''): string {
        return value === null ? '-' : `${value.toLocaleString('de-DE')}${suffix}`;
    }
}
