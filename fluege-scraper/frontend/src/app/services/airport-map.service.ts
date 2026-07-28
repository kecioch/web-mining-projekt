import {
    ApplicationRef,
    ComponentRef,
    createComponent,
    EnvironmentInjector,
    inject,
    Injectable,
} from '@angular/core';
import { divIcon, DivIcon, featureGroup, latLng, Map, marker, TileLayer, tileLayer } from 'leaflet';

import { AirportMarkerComponent } from '../components/airport-marker/airport-marker.component';
import { Airport } from '../models/airport';

export type AirportMapTheme = 'light' | 'dark';

@Injectable()
export class AirportMapService {
    private readonly applicationRef = inject(ApplicationRef);
    private readonly environmentInjector = inject(EnvironmentInjector);
    private baseLayer = this.createBaseLayer('light');

    readonly options = {
        layers: [this.baseLayer],
        zoom: 5,
        center: latLng([51.3755, 7.7028]), // Zentrum von Deutschland
    };

    private readonly airportLayer = featureGroup();
    private map: Map | null = null;

    connect(map: Map): void {
        this.map = map;
        this.airportLayer.addTo(map);
    }

    setTheme(theme: AirportMapTheme): void {
        if (!this.map) {
            return;
        }

        this.map.removeLayer(this.baseLayer);
        this.baseLayer = this.createBaseLayer(theme);
        this.baseLayer.addTo(this.map).bringToBack();
    }

    renderAirports(airports: Airport[], onSelect: (airport: Airport) => void): number {
        this.airportLayer.clearLayers();
        let renderedMarkers = 0;

        for (const airport of airports) {
            if (!this.hasValidCoordinates(airport)) {
                continue;
            }

            const { componentRef, icon } = this.createAirportIcon(airport);
            const airportMarker = marker([airport.latitude, airport.longitude], {
                icon,
                keyboard: true,
                title: `${airport.airport_name} (${airport.iata_code ?? '-'})`,
            }).addTo(this.airportLayer);

            airportMarker.once('remove', () => this.destroyMarkerComponent(componentRef));

            const tooltip = document.createElement('span');
            tooltip.textContent = `${airport.airport_name} (${airport.iata_code ?? '-'})`;
            airportMarker.bindTooltip(tooltip);
            airportMarker.on('click', () => onSelect(airport));
            renderedMarkers += 1;
        }

        return renderedMarkers;
    }

    disconnect(): void {
        this.airportLayer.clearLayers();
        this.airportLayer.remove();
        this.map = null;
    }

    private createAirportIcon(airport: Airport): {
        componentRef: ComponentRef<AirportMarkerComponent>;
        icon: DivIcon;
    } {
        const hostElement = document.createElement('app-airport-marker');
        const componentRef = createComponent(AirportMarkerComponent, {
            environmentInjector: this.environmentInjector,
            hostElement,
        });
        componentRef.setInput('code', airport.iata_code);
        this.applicationRef.attachView(componentRef.hostView);
        componentRef.changeDetectorRef.detectChanges();

        return {
            componentRef,
            icon: divIcon({
                className: 'airport-plane-marker',
                html: hostElement,
                iconSize: [58, 30],
                iconAnchor: [29, 15],
                tooltipAnchor: [0, -18],
            }),
        };
    }

    private destroyMarkerComponent(componentRef: ComponentRef<AirportMarkerComponent>): void {
        this.applicationRef.detachView(componentRef.hostView);
        componentRef.destroy();
    }

    private createBaseLayer(theme: AirportMapTheme): TileLayer {
        const style = theme === 'dark' ? 'dark_all' : 'light_all';

        return tileLayer(`https://{s}.basemaps.cartocdn.com/${style}/{z}/{x}/{y}{r}.png`, {
            maxZoom: 19,
            attribution:
                '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        });
    }

    private hasValidCoordinates(
        airport: Airport,
    ): airport is Airport & { latitude: number; longitude: number } {
        return (
            typeof airport.latitude === 'number' &&
            Number.isFinite(airport.latitude) &&
            typeof airport.longitude === 'number' &&
            Number.isFinite(airport.longitude)
        );
    }
}
