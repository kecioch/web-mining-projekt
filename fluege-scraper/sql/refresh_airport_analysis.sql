-- Hier befindet sich das Skript, das einmalig im Supabase SQL Editor ausgeführt werden muss.
-- Es berechnet die Tagesanalyse vollständig neu und kann daher sicher wiederholt werden.

CREATE OR REPLACE FUNCTION public.refresh_airport_analysis(
    p_analysis_date date,
    p_delay_threshold integer DEFAULT 15
)
RETURNS integer
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    inserted_rows integer;
BEGIN
    -- Prüft, ob ein gültiges Datum und ein sinnvoller Grenzwert übergeben wurden
    IF p_analysis_date IS NULL THEN
        RAISE EXCEPTION 'p_analysis_date darf nicht NULL sein';
    END IF;

    IF p_delay_threshold < 0 THEN
        RAISE EXCEPTION 'p_delay_threshold darf nicht negativ sein';
    END IF;

    -- Löscht die alte Tagesanalyse, damit eine erneute Berechnung keine doppelten Werte erzeugt
    DELETE FROM public.airport_analysis
    WHERE analysis_date = p_analysis_date;

    -- Sammelt alle Ankünfte und Abflüge des Tages
    WITH movements AS (
        SELECT
            airport_icao,
            'ARRIVAL'::public.flight_direction AS flight_direction,
            delay_minutes,
            arrival_status AS status
        FROM public.arrivals
        WHERE scheduled_arrival_at >=
                  (p_analysis_date::timestamp AT TIME ZONE 'Europe/Berlin')
          AND scheduled_arrival_at <
                  ((p_analysis_date + 1)::timestamp AT TIME ZONE 'Europe/Berlin')
          AND airport_icao IS NOT NULL

        -- Fügt die Abflüge zu den zuvor ausgewählten Ankünften hinzu
        UNION ALL

        SELECT
            airport_icao,
            'DEPARTURE'::public.flight_direction AS flight_direction,
            delay_minutes,
            departure_status AS status
        FROM public.departures
        WHERE scheduled_departure_at >=
                  (p_analysis_date::timestamp AT TIME ZONE 'Europe/Berlin')
          AND scheduled_departure_at <
                  ((p_analysis_date + 1)::timestamp AT TIME ZONE 'Europe/Berlin')
          AND airport_icao IS NOT NULL
    ),
    -- Erkennt anhand des Status, ob ein Flug annulliert oder gestrichen wurde
    classified AS (
        SELECT
            *,
            lower(coalesce(status, '')) ~ '(annull|gestrich|cancel)' AS cancelled
        FROM movements
    ),
    -- Berechnet die täglichen Kennzahlen getrennt nach Flughafen und Flugrichtung
    daily AS (
        SELECT
            airport_icao,
            flight_direction,
            count(*)::integer AS flight_count,
            count(*) FILTER (
                WHERE NOT cancelled AND delay_minutes IS NOT NULL
            )::integer AS evaluated_flight_count,
            count(*) FILTER (
                WHERE NOT cancelled
                  AND delay_minutes IS NOT NULL
                  AND delay_minutes > p_delay_threshold
            )::integer AS delayed_flight_count,
            count(*) FILTER (
                WHERE NOT cancelled
                  AND delay_minutes IS NOT NULL
                  AND delay_minutes <= p_delay_threshold
            )::integer AS on_time_flight_count,
            count(*) FILTER (WHERE cancelled)::integer AS cancelled_flight_count,
            coalesce(
                sum(greatest(delay_minutes, 0)) FILTER (
                    WHERE NOT cancelled AND delay_minutes IS NOT NULL
                ),
                0
            )::integer AS total_delay_minutes,
            round(
                avg(greatest(delay_minutes, 0)) FILTER (
                    WHERE NOT cancelled AND delay_minutes IS NOT NULL
                ),
                2
            ) AS average_delay_minutes
        FROM classified
        GROUP BY airport_icao, flight_direction
    )
    -- Speichert die fertig berechneten Tageswerte in der Analysetabelle
    INSERT INTO public.airport_analysis (
        analysis_date,
        airport_icao,
        flight_direction,
        flight_count,
        evaluated_flight_count,
        delayed_flight_count,
        on_time_flight_count,
        cancelled_flight_count,
        total_delay_minutes,
        average_delay_minutes,
        calculated_at
    )
    SELECT
        p_analysis_date,
        airport_icao,
        flight_direction,
        flight_count,
        evaluated_flight_count,
        delayed_flight_count,
        on_time_flight_count,
        cancelled_flight_count,
        total_delay_minutes,
        average_delay_minutes,
        now()
    FROM daily;

    -- Rückgabe wie viele Analysezeilen für diesen Tag erstellt wurden
    GET DIAGNOSTICS inserted_rows = ROW_COUNT;
    RETURN inserted_rows;
END;
$$;

-- Verhindert, dass normale oder nicht angemeldete Nutzer die Berechnung starten
REVOKE ALL ON FUNCTION public.refresh_airport_analysis(date, integer)
FROM PUBLIC, anon, authenticated;

-- Nur die GitHub Action mit dem Service-Role-Schlüssel darf die Funktion ausführen
GRANT EXECUTE ON FUNCTION public.refresh_airport_analysis(date, integer)
TO service_role;
