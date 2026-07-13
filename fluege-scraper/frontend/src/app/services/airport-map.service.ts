import { Injectable } from '@angular/core';
import { divIcon, featureGroup, latLng, Map, marker, TileLayer, tileLayer } from 'leaflet';

import { Airport } from '../models/airport';

export type AirportMapTheme = 'light' | 'dark';

@Injectable()
export class AirportMapService {
    private baseLayer = this.createBaseLayer('light');

    readonly options = {
        layers: [this.baseLayer],
        zoom: 5,
        center: latLng([51.3755, 7.7028]),
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

            const airportMarker = marker([airport.latitude, airport.longitude], {
                icon: this.createAirportIcon(airport),
                keyboard: true,
                title: `${airport.airport_name} (${airport.iata_code ?? '-'})`,
            }).addTo(this.airportLayer);

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

    private createAirportIcon(airport: Airport) {
        const airportCode = (airport.iata_code ?? 'AIR').replace(/[^A-Z0-9]/g, '');

        return divIcon({
            className: 'airport-plane-marker',
            html: `
                <span class="airport-plane-marker__content" aria-hidden="true">
                    <svg viewBox="0 0 24 24" focusable="false">
                        <path d="M10.18 9 2 3.5V2l10 3 10-3v1.5L13.82 9 22 14.5V16l-10-3-10 3v-1.5L10.18 9z"></path>
                    </svg>
                    <span class="airport-plane-marker__code">${airportCode}</span>
                </span>
            `,
            iconSize: [58, 30],
            iconAnchor: [29, 15],
            tooltipAnchor: [0, -18],
        });
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
