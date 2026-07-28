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
            { label: 'ICAO-Code', value: airport.icao_code ?? '-' },
            { label: 'Betreiber', value: airport.operator ?? '-' },
            { label: 'Passagiere', value: this.formatNumber(airport.passengers) },
            {
                label: 'Flugbewegungen',
                value: this.formatNumber(airport.aircraft_movements),
            },
            { label: 'Fracht', value: this.formatNumber(airport.freight_tons, ' t') },
            {
                label: 'Start-/Landebahnen',
                value: airport.runways?.toString() ?? '-',
            },
            {
                label: 'Höhe',
                value: airport.detail_elevation ?? airport.elevation ?? '-',
            },
            {
                label: 'Eröffnung',
                value: airport.detail_opened ?? airport.opened ?? '-',
            },
            {
                label: 'Fläche',
                value:
                    airport.detail_area ??
                    (airport.area_ha === null ? '-' : `${airport.area_ha} ha`),
            },
            { label: 'Terminals', value: airport.terminals ?? '-' },
        ];
    });

    private formatNumber(value: number | null, suffix = ''): string {
        return value === null ? '-' : `${value.toLocaleString('de-DE')}${suffix}`;
    }
}
