import type { AirportSourceRecord } from '../domain/airport.js';
import type { AirportRepository } from './airport.repository.js';

interface CacheEntry {
    expiresAt: number;
    value: AirportSourceRecord[];
}

export class CachedAirportRepository implements AirportRepository {
    private readonly cache = new Map<string, CacheEntry>();
    private readonly inFlight = new Map<string, Promise<AirportSourceRecord[]>>();

    constructor(
        private readonly inner: AirportRepository,
        private readonly ttlMs = Number(process.env['AIRPORT_CACHE_TTL_MS'] ?? 5 * 60 * 1000),
    ) {}

    public findAll(): Promise<AirportSourceRecord[]> {
        return this.getCached('all', () => this.inner.findAll());
    }

    public findTracked(): Promise<AirportSourceRecord[]> {
        return this.getCached('tracked', () => this.inner.findTracked());
    }

    public invalidate(): void {
        this.cache.clear();
    }

    private async getCached(
        key: string,
        loader: () => Promise<AirportSourceRecord[]>,
    ): Promise<AirportSourceRecord[]> {
        const entry = this.cache.get(key);

        if (entry && entry.expiresAt > Date.now()) {
            return entry.value;
        }

        const pending = this.inFlight.get(key);

        if (pending) {
            return pending;
        }

        const request = loader()
            .then((value) => {
                this.cache.set(key, { value, expiresAt: Date.now() + this.ttlMs });
                return value;
            })
            .finally(() => {
                this.inFlight.delete(key);
            });

        this.inFlight.set(key, request);

        return request;
    }
}
