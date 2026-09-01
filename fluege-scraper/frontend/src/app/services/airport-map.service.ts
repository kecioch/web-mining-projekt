import {
    ApplicationRef,
    ComponentRef,
    createComponent,
    EnvironmentInjector,
    inject,
    Injectable,
} from '@angular/core';
import {
    circleMarker,
    CircleMarker,
    divIcon,
    DivIcon,
    featureGroup,
    latLng,
    latLngBounds,
    Map as LeafletMap,
    marker,
    Polyline,
    polyline,
    TileLayer,
    tileLayer,
} from 'leaflet';

import { AirportMarkerComponent } from '../components/airport-marker/airport-marker.component';
import { Airport } from '../models/airport';
import { AirportConnections, ConnectionCount } from '../models/connection';

const DEPARTURE_COLOR = '#f97316';
const ARRIVAL_COLOR = '#3b82f6';
const BIDIRECTIONAL_COLOR = '#8b5cf6';
const FOCUS_ZOOM = 6;
const INITIAL_CENTER: [number, number] = [51.3755, 7.7028]; // Zentrum von Deutschland
const INITIAL_ZOOM = 5;
const DOT_RADIUS = 3;
const DOT_RADIUS_HOVER = 6;

export type AirportMapTheme = 'light' | 'dark';

interface MergedConnection {
    connection: Airport;
    departureCount: number;
    arrivalCount: number;
}

interface RenderedConnection {
    line: Polyline;
    dot: CircleMarker;
    color: string;
    resetTimer: ReturnType<typeof setTimeout> | null;
}

@Injectable()
export class AirportMapService {
    private readonly applicationRef = inject(ApplicationRef);
    private readonly environmentInjector = inject(EnvironmentInjector);
    private baseLayer = this.createBaseLayer('light');

    readonly options = {
        layers: [this.baseLayer],
        zoom: INITIAL_ZOOM,
        zoomSnap: 0.25,
        minZoom: 3,
        maxBounds: latLngBounds([-85, -180], [85, 300]),
        maxBoundsViscosity: 1,
        worldCopyJump: false,
        center: latLng(INITIAL_CENTER),
    };

    private readonly airportLayer = featureGroup();
    private readonly connectionLayer = featureGroup();
    private map: LeafletMap | null = null;

    private airports: Airport[] = [];
    private onSelect: (airport: Airport) => void = () => {};
    private backgroundClickHandler: () => void = () => {};
    private activeHover: RenderedConnection | null = null;
    private renderedLines: RenderedConnection[] = [];

    connect(map: LeafletMap): void {
        this.map = map;
        this.connectionLayer.addTo(map);
        this.airportLayer.addTo(map);
        map.on('click', () => this.backgroundClickHandler());
        map.on('movestart', () => this.clearActiveHover());
        map.on('moveend', () => this.resetAllConnections());
    }

    setBackgroundClickHandler(handler: () => void): void {
        this.backgroundClickHandler = handler;
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
        this.airports = airports;
        this.onSelect = onSelect;
        return this.renderAirportMarkers(airports);
    }

    focusAirport(airport: Airport): void {
        this.renderAirportMarkers([airport]);

        if (this.map && this.hasValidCoordinates(airport)) {
            this.centerInVisibleArea([airport.latitude, airport.longitude], FOCUS_ZOOM);
        }
    }

    resetAirports(): void {
        this.renderAirportMarkers(this.airports);

        this.map?.setView(INITIAL_CENTER, INITIAL_ZOOM, { animate: true });
    }

    renderConnections(origin: Airport, connections: AirportConnections): number {
        this.activeHover = null;
        this.renderedLines = [];
        this.connectionLayer.clearLayers();

        if (!this.hasValidCoordinates(origin)) {
            return 0;
        }

        const originLatLng: [number, number] = [origin.latitude, origin.longitude];
        const endpoints: [number, number][] = [];

        for (const merged of this.mergeConnections(connections)) {
            const connection = merged.connection;
            if (!this.hasValidCoordinates(connection)) {
                continue;
            }

            const color = this.lineColor(merged);
            const connectionLatLng: [number, number] = [connection.latitude, connection.longitude];

            const line = polyline([originLatLng, connectionLatLng], {
                className: 'connection-line',
                color,
                weight: 2,
                opacity: 0.7,
                bubblingMouseEvents: false,
            }).addTo(this.connectionLayer);

            line.bindTooltip(this.tooltipHtml(merged), { sticky: true });

            const connectionDot = circleMarker(connectionLatLng, {
                radius: DOT_RADIUS,
                color,
                weight: 2,
                fillColor: color,
                fillOpacity: 0.9,
                bubblingMouseEvents: false,
            }).addTo(this.connectionLayer);

            const entry: RenderedConnection = { line, dot: connectionDot, color, resetTimer: null };

            line.on('mouseover', () => this.enterConnection(entry));
            line.on('mouseout', () => this.leaveConnection(entry));
            connectionDot.on('mouseover', () => this.enterConnection(entry));
            connectionDot.on('mouseout', () => this.leaveConnection(entry));
            line.on('tooltipopen', () => this.closeOtherTooltips(line));

            this.renderedLines.push(entry);
            endpoints.push(connectionLatLng);
        }

        this.fitToConnections(originLatLng, endpoints);

        return endpoints.length;
    }

    private fitToConnections(originLatLng: [number, number], endpoints: [number, number][]): void {
        if (!this.map) {
            return;
        }

        if (endpoints.length === 0) {
            this.centerInVisibleArea(originLatLng, FOCUS_ZOOM);
            return;
        }

        const rightPadding = this.getDrawerWidth();
        const bounds = latLngBounds([originLatLng, ...endpoints]);

        this.map.fitBounds(bounds, {
            paddingTopLeft: [30, 30],
            paddingBottomRight: [rightPadding + 30, 30],
            animate: true,
        });
    }

    private centerInVisibleArea(target: [number, number], zoom: number): void {
        if (!this.map) {
            return;
        }

        this.map.setView(target, zoom, { animate: false });
        this.map.panBy([this.getDrawerWidth() / 2, 0], { animate: false });
    }

    private getDrawerWidth(): number {
        const drawer =
            document.querySelector<HTMLElement>('.airport-drawer') ??
            document.querySelector<HTMLElement>('.p-drawer');
        return drawer?.offsetWidth ?? 0;
    }

    clearConnections(): void {
        this.activeHover = null;
        this.renderedLines = [];
        this.connectionLayer.clearLayers();
    }

    disconnect(): void {
        this.airportLayer.clearLayers();
        this.airportLayer.remove();
        this.connectionLayer.clearLayers();
        this.connectionLayer.remove();
        this.map = null;
    }

    private renderAirportMarkers(airports: Airport[]): number {
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
                title: `${airport.name} (${airport.icao ?? '-'})`,
            }).addTo(this.airportLayer);

            airportMarker.once('remove', () => this.destroyMarkerComponent(componentRef));

            const tooltip = document.createElement('span');
            tooltip.textContent = `${airport.name} (${airport.icao ?? '-'})`;
            airportMarker.bindTooltip(tooltip, { direction: 'right' });
            airportMarker.on('click', () => this.onSelect(airport));
            renderedMarkers += 1;
        }

        return renderedMarkers;
    }

    private mergeConnections(connections: AirportConnections): MergedConnection[] {
        const byIcao = new Map<string, MergedConnection>();

        const add = (item: ConnectionCount, direction: 'departure' | 'arrival'): void => {
            const existing = byIcao.get(item.connection.icao);
            if (existing) {
                if (direction === 'departure') {
                    existing.departureCount += item.count;
                } else {
                    existing.arrivalCount += item.count;
                }
                return;
            }

            byIcao.set(item.connection.icao, {
                connection: item.connection,
                departureCount: direction === 'departure' ? item.count : 0,
                arrivalCount: direction === 'arrival' ? item.count : 0,
            });
        };

        for (const departure of connections.departures) {
            add(departure, 'departure');
        }
        for (const arrival of connections.arrivals) {
            add(arrival, 'arrival');
        }

        return [...byIcao.values()];
    }

    private lineColor(merged: MergedConnection): string {
        if (merged.departureCount > 0 && merged.arrivalCount > 0) {
            return BIDIRECTIONAL_COLOR;
        }
        return merged.departureCount > 0 ? DEPARTURE_COLOR : ARRIVAL_COLOR;
    }

    private tooltipHtml(merged: MergedConnection): string {
        const connection = merged.connection;
        const code = connection.iata ?? connection.icao;
        const title = connection.name ? `${connection.name} (${code})` : code;

        const lines: string[] = [];
        if (merged.departureCount > 0) {
            lines.push(`&#8592; ${merged.departureCount} Abflüge`);
        }
        if (merged.arrivalCount > 0) {
            lines.push(`&#8594; ${merged.arrivalCount} Ankünfte`);
        }

        return `<strong>${title}</strong><br>${lines.join('<br>')}`;
    }

    private enterConnection(entry: RenderedConnection): void {
        if (entry.resetTimer) {
            clearTimeout(entry.resetTimer);
            entry.resetTimer = null;
        }

        if (this.activeHover && this.activeHover.line !== entry.line) {
            this.clearActiveHover();
        }

        entry.line.setStyle({ weight: 5, opacity: 1 });
        entry.dot.setRadius(DOT_RADIUS_HOVER);
        entry.dot.bringToFront();
        entry.line.openTooltip(entry.dot.getLatLng());
        this.activeHover = entry;
    }

    private leaveConnection(entry: RenderedConnection): void {
        if (entry.resetTimer) {
            clearTimeout(entry.resetTimer);
        }
        entry.resetTimer = setTimeout(() => {
            entry.resetTimer = null;
            this.resetConnection(entry);
        }, 0);
    }

    private resetConnection(entry: RenderedConnection): void {
        entry.line.closeTooltip();
        entry.line.setStyle({ weight: 2, opacity: 0.7, color: entry.color });
        entry.dot.setRadius(DOT_RADIUS);

        if (this.activeHover?.line === entry.line) {
            this.activeHover = null;
        }
    }

    private clearActiveHover(): void {
        if (this.activeHover) {
            this.resetConnection(this.activeHover);
        }
    }

    private closeOtherTooltips(current: Polyline): void {
        for (const entry of this.renderedLines) {
            if (entry.line === current) {
                continue;
            }
            this.resetEntry(entry);
        }
    }

    private resetAllConnections(): void {
        this.activeHover = null;
        for (const entry of this.renderedLines) {
            this.resetEntry(entry);
        }
    }

    private resetEntry(entry: RenderedConnection): void {
        if (entry.resetTimer) {
            clearTimeout(entry.resetTimer);
            entry.resetTimer = null;
        }
        entry.line.closeTooltip();
        entry.line.setStyle({ weight: 2, opacity: 0.7, color: entry.color });
        entry.dot.setRadius(DOT_RADIUS);
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
        componentRef.setInput('code', airport.icao);
        this.applicationRef.attachView(componentRef.hostView);
        componentRef.changeDetectorRef.detectChanges();

        return {
            componentRef,
            icon: divIcon({
                className: 'airport-plane-marker',
                html: hostElement,
                iconSize: [58, 30],
                iconAnchor: [29, 15],
                tooltipAnchor: [38, 0],
            }),
        };
    }

    private destroyMarkerComponent(componentRef: ComponentRef<AirportMarkerComponent>): void {
        this.applicationRef.detachView(componentRef.hostView);
        componentRef.destroy();
    }

    private createBaseLayer(theme: AirportMapTheme): TileLayer {
        const style = theme === 'dark' ? 'alidade_smooth_dark' : 'osm_bright';

        return tileLayer(
            `https://tiles.stadiamaps.com/tiles/${style}/{z}/{x}/{y}{r}.png`,
            {
                maxZoom: 10,
                minZoom: 3,
                noWrap: true,
                bounds: latLngBounds([-85, -180], [85, 180]),
                attribution:
                    '&copy; <a href="https://www.stadiamaps.com/" target="_blank">Stadia Maps</a> &copy; <a href="https://openmaptiles.org/" target="_blank">OpenMapTiles</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            },
        );
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
