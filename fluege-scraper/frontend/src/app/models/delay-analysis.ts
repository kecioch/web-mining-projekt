export interface DelayMetric {
    flightCount: number;
    evaluatedFlightCount: number;
    onTimeFlightCount: number;
    delayedFlightCount: number;
    cancelledFlightCount: number;
    coverageRate: number | null;
    onTimeRate: number | null;
    delayRate: number | null;
    cancellationRate: number | null;
    averageDelayMinutes: number | null;
}

export interface DailyDelayAnalysis {
    date: string;
    arrival: DelayMetric | null;
    departure: DelayMetric | null;
}

export interface AirportDelayAnalysis {
    summary: DelayMetric;
    arrivalSummary?: DelayMetric;
    departureSummary?: DelayMetric;
    daily: DailyDelayAnalysis[];
    period: {
        from: string;
        to: string;
    } | null;
    delayThresholdMinutes: number;
}
