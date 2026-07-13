import { DecimalPipe } from '@angular/common';
import { Component, inject, OnDestroy, signal } from '@angular/core';
import { LeafletModule } from '@bluehalo/ngx-leaflet';
import { Map } from 'leaflet';
import { DrawerModule } from 'primeng/drawer';
import { take } from 'rxjs';

import { Airport } from '../../models/airport';
import { AirportMapService, AirportMapTheme } from '../../services/airport-map.service';
import { AirportService } from '../../services/airport.service';

@Component({
    selector: 'app-airport-map-page',
    imports: [DecimalPipe, DrawerModule, LeafletModule],
    providers: [AirportMapService],
    templateUrl: './airport-map.page.html',
    styleUrl: './airport-map.page.scss',
})
export class AirportMapPage implements OnDestroy {
    private readonly airportService = inject(AirportService);
    private readonly airportMapService = inject(AirportMapService);

    protected readonly mapOptions = this.airportMapService.options;
    protected readonly drawerVisible = signal(false);
    protected readonly selectedAirport = signal<Airport | null>(null);
    protected readonly airportCount = signal(0);
    protected readonly loadingAirports = signal(true);
    protected readonly loadError = signal<string | null>(null);
    protected readonly mapTheme = signal<AirportMapTheme>('light');

    protected onMapReady(map: Map): void {
        this.airportMapService.connect(map);
        this.airportMapService.setTheme(this.mapTheme());
        this.loadAirports();
    }

    protected toggleMapTheme(): void {
        const nextTheme: AirportMapTheme = this.mapTheme() === 'light' ? 'dark' : 'light';
        this.mapTheme.set(nextTheme);
        this.airportMapService.setTheme(nextTheme);
    }

    protected setDrawerVisibility(visible: boolean): void {
        this.drawerVisible.set(visible);
        if (!visible) {
            this.selectedAirport.set(null);
        }
    }

    ngOnDestroy(): void {
        this.airportMapService.disconnect();
    }

    private loadAirports(): void {
        this.loadingAirports.set(true);
        this.loadError.set(null);

        this.airportService
            .getAirports()
            .pipe(take(1))
            .subscribe({
                next: (airports) => {
                    const renderedMarkers = this.airportMapService.renderAirports(
                        airports,
                        (airport) => this.openAirportDetails(airport),
                    );
                    this.airportCount.set(renderedMarkers);
                    this.loadingAirports.set(false);
                },
                error: () => {
                    this.loadingAirports.set(false);
                    this.loadError.set('Die Flughafendaten konnten nicht geladen werden.');
                },
            });
    }

    private openAirportDetails(airport: Airport): void {
        this.selectedAirport.set(airport);
        this.drawerVisible.set(true);
    }
}
