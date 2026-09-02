export interface AnalysisPeriodRepository {
    findLatestMovementAt(airportIcao: string): Promise<Date | null>;
}
