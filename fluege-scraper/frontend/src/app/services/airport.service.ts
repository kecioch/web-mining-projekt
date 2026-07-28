import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { Airport } from '../models/airport';

@Injectable({ providedIn: 'root' })
export class AirportService {
    private readonly http = inject(HttpClient);

    public getAirports(): Observable<Airport[]> {
        return this.http.get<Airport[]>('/api/airports');
    }
}
