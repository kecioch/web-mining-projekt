export interface DelayMetric {
    flightCount: number;
    evaluatedFlightCount: number;
    delayedFlightCount: number;
    cancelledFlightCount: number;
    coverageRate: number | null;
    delayRate: number | null;
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
