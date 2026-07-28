import { Component, computed, input } from '@angular/core';

@Component({
    selector: 'app-airport-marker',
    templateUrl: './airport-marker.component.html',
    styleUrl: './airport-marker.component.scss',
})
export class AirportMarkerComponent {
    readonly code = input<string | null>(null);

    protected readonly airportCode = computed(() =>
        (this.code() ?? 'AIR').replace(/[^A-Z0-9]/g, ''),
    );
}
