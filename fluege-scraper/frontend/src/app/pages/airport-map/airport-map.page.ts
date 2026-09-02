import { Component, inject, OnDestroy, signal } from '@angular/core';
import { LeafletModule } from '@bluehalo/ngx-leaflet';
import { Map } from 'leaflet';
import { ButtonModule } from 'primeng/button';
import { DrawerModule } from 'primeng/drawer';
import { take } from 'rxjs';

import { AirportDetailsComponent } from '../../components/airport-details/airport-details.component';
import { AirportAircraft } from '../../models/aircraft';
import { AirportAirlines } from '../../models/airline';
import { Airport } from '../../models/airport';
import { AirportConnections, ConnectionRange } from '../../models/connection';
import { AirportDelayAnalysis } from '../../models/delay-analysis';
import { AirportMapService, AirportMapTheme } from '../../services/airport-map.service';
import { AirportService } from '../../services/airport.service';

@Component({
    selector: 'app-airport-map-page',
    imports: [AirportDetailsComponent, ButtonModule, DrawerModule, LeafletModule],
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
    protected readonly connections = signal<AirportConnections | null>(null);
    protected readonly loadingConnections = signal(false);
    protected readonly connectionsError = signal<string | null>(null);
    protected readonly airlines = signal<AirportAirlines | null>(null);
    protected readonly loadingAirlines = signal(false);
    protected readonly airlinesError = signal<string | null>(null);
    protected readonly aircraft = signal<AirportAircraft | null>(null);
    protected readonly loadingAircraft = signal(false);
    protected readonly aircraftError = signal<string | null>(null);
    protected readonly delayAnalysis = signal<AirportDelayAnalysis | null>(null);
    protected readonly loadingDelayAnalysis = signal(false);
    protected readonly delayAnalysisError = signal<string | null>(null);
    protected readonly range = signal<ConnectionRange>('7d');
    protected readonly airportCount = signal(0);
    protected readonly loadingAirports = signal(true);
    protected readonly loadError = signal<string | null>(null);
    protected readonly mapTheme = signal<AirportMapTheme>('light');

    protected onMapReady(map: Map): void {
        this.airportMapService.connect(map);
        this.airportMapService.setTheme(this.mapTheme());
        this.airportMapService.setBackgroundClickHandler(() => this.closeDrawer());
        this.loadAirports();
    }

    protected toggleMapTheme(): void {
        const nextTheme: AirportMapTheme = this.mapTheme() === 'light' ? 'dark' : 'light';
        this.mapTheme.set(nextTheme);
        this.airportMapService.setTheme(nextTheme);
    }

    protected setDrawerVisibility(visible: boolean): void {
        if (!visible) {
            this.closeDrawer();
            return;
        }
        this.drawerVisible.set(true);
    }

    protected onRangeChange(range: ConnectionRange): void {
        this.range.set(range);
        const airport = this.selectedAirport();
        if (airport) {
            this.loadConnections(airport);
            this.loadAirlines(airport);
            this.loadAircraft(airport);
            this.loadDelayAnalysis(airport);
        }
    }

    ngOnDestroy(): void {
        this.airportMapService.disconnect();
    }

    private closeDrawer(): void {
        if (!this.selectedAirport() && !this.drawerVisible()) {
            return;
        }
        this.drawerVisible.set(false);
        this.selectedAirport.set(null);
        this.connections.set(null);
        this.connectionsError.set(null);
        this.airlines.set(null);
        this.airlinesError.set(null);
        this.aircraft.set(null);
        this.aircraftError.set(null);
        this.delayAnalysis.set(null);
        this.delayAnalysisError.set(null);
        this.airportMapService.clearConnections();
        this.airportMapService.resetAirports();
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
        this.airportMapService.focusAirport(airport);
        this.loadConnections(airport);
        this.loadAirlines(airport);
        this.loadAircraft(airport);
        this.loadDelayAnalysis(airport);
    }

    private loadConnections(airport: Airport): void {
        this.connections.set(null);
        this.connectionsError.set(null);
        this.airportMapService.clearConnections();

        if (!airport.icao) {
            return;
        }

        this.loadingConnections.set(true);
        const range = this.range();

        this.airportService
            .getConnections(airport.icao, range)
            .pipe(take(1))
            .subscribe({
                next: (connections) => {
                    if (!this.isCurrentRequest(airport, range)) {
                        return;
                    }
                    this.connections.set(connections);
                    this.airportMapService.renderConnections(airport, connections);
                    this.loadingConnections.set(false);
                },
                error: () => {
                    if (!this.isCurrentRequest(airport, range)) {
                        return;
                    }
                    this.loadingConnections.set(false);
                    this.connectionsError.set('Die Verbindungen konnten nicht geladen werden.');
                },
            });
    }

    private loadAirlines(airport: Airport): void {
        this.airlines.set(null);
        this.airlinesError.set(null);

        if (!airport.icao) {
            return;
        }

        this.loadingAirlines.set(true);
        const range = this.range();

        this.airportService
            .getAirlines(airport.icao, range)
            .pipe(take(1))
            .subscribe({
                next: (airlines) => {
                    if (!this.isCurrentRequest(airport, range)) {
                        return;
                    }
                    this.airlines.set(airlines);
                    this.loadingAirlines.set(false);
                },
                error: () => {
                    if (!this.isCurrentRequest(airport, range)) {
                        return;
                    }
                    this.loadingAirlines.set(false);
                    this.airlinesError.set('Die Airlines konnten nicht geladen werden.');
                },
            });
    }

    private loadAircraft(airport: Airport): void {
        this.aircraft.set(null);
        this.aircraftError.set(null);

        if (!airport.icao) {
            return;
        }

        this.loadingAircraft.set(true);
        const range = this.range();

        this.airportService
            .getAircraft(airport.icao, range)
            .pipe(take(1))
            .subscribe({
                next: (aircraft) => {
                    if (!this.isCurrentRequest(airport, range)) {
                        return;
                    }
                    this.aircraft.set(aircraft);
                    this.loadingAircraft.set(false);
                },
                error: () => {
                    if (!this.isCurrentRequest(airport, range)) {
                        return;
                    }
                    this.loadingAircraft.set(false);
                    this.aircraftError.set('Die Flugzeugtypen konnten nicht geladen werden.');
                },
            });
    }

    private loadDelayAnalysis(airport: Airport): void {
        this.delayAnalysis.set(null);
        this.delayAnalysisError.set(null);

        if (!airport.icao) {
            return;
        }

        this.loadingDelayAnalysis.set(true);
        const range = this.range();
        this.airportService
            .getDelayAnalysis(airport.icao, range)
            .pipe(take(1))
            .subscribe({
                next: (analysis) => {
                    if (!this.isCurrentRequest(airport, range)) {
                        return;
                    }
                    this.delayAnalysis.set(analysis);
                    this.loadingDelayAnalysis.set(false);
                },
                error: () => {
                    if (!this.isCurrentRequest(airport, range)) {
                        return;
                    }
                    this.loadingDelayAnalysis.set(false);
                    this.delayAnalysisError.set(
                        'Die Verspätungsanalyse konnte nicht geladen werden.',
                    );
                },
            });
    }

    private isCurrentRequest(airport: Airport, range: ConnectionRange): boolean {
        return this.selectedAirport()?.icao === airport.icao && this.range() === range;
    }
}
