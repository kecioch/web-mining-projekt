import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { Airport } from '../models/airport';
import { AirportConnections, ConnectionRange } from '../models/connection';

@Injectable({ providedIn: 'root' })
export class AirportService {
    private readonly http = inject(HttpClient);

    public getAirports(): Observable<Airport[]> {
        return this.http.get<Airport[]>('/api/airports/tracked');
    }

    public getConnections(icao: string, range: ConnectionRange): Observable<AirportConnections> {
        return this.http.get<AirportConnections>(
            `/api/airports/${encodeURIComponent(icao)}/connections`,
            { params: { range } },
        );
    }
}
