create or replace function public.airport_delay_analysis_hourly(
    p_icao text,
    p_from timestamptz,
    p_delay_threshold integer default 15
)
returns table (
    bucket_start timestamp,
    flight_direction text,
    flight_count bigint,
    evaluated_flight_count bigint,
    delayed_flight_count bigint,
    cancelled_flight_count bigint,
    total_delay_minutes bigint
)
language sql
stable
set search_path = public
as $$
    with movements as (
        select
            coalesce(ar.scheduled_arrival_at, ar.scraped_at) as movement_at,
            'ARRIVAL'::text as flight_direction,
            ar.delay_minutes,
            ar.arrival_status as status
        from public.arrivals ar
        where ar.airport_icao = upper(p_icao)
          and coalesce(ar.scheduled_arrival_at, ar.scraped_at) >= p_from

        union all

        select
            coalesce(d.scheduled_departure_at, d.scraped_at) as movement_at,
            'DEPARTURE'::text as flight_direction,
            d.delay_minutes,
            d.departure_status as status
        from public.departures d
        where d.airport_icao = upper(p_icao)
          and coalesce(d.scheduled_departure_at, d.scraped_at) >= p_from
    ),
    classified as (
        select
            date_trunc('hour', movement_at at time zone 'Europe/Berlin') as bucket_start,
            flight_direction,
            delay_minutes,
            lower(coalesce(status, '')) ~ '(annull|gestrich|cancel)' as cancelled
        from movements
    ),
    grid as (
        select g.bucket_start, d.flight_direction
        from generate_series(
            date_trunc('hour', (p_from at time zone 'Europe/Berlin')),
            date_trunc('hour', (now() at time zone 'Europe/Berlin')),
            interval '1 hour'
        ) as g(bucket_start)
        cross join (values ('ARRIVAL'), ('DEPARTURE')) as d(flight_direction)
    )
    select
        grid.bucket_start,
        grid.flight_direction,
        count(c.*) as flight_count,
        count(*) filter (
            where not c.cancelled and c.delay_minutes is not null
        ) as evaluated_flight_count,
        count(*) filter (
            where not c.cancelled
              and c.delay_minutes is not null
              and c.delay_minutes > p_delay_threshold
        ) as delayed_flight_count,
        count(*) filter (where c.cancelled) as cancelled_flight_count,
        coalesce(
            sum(greatest(c.delay_minutes, 0)) filter (
                where not c.cancelled and c.delay_minutes is not null
            ),
            0
        )::bigint as total_delay_minutes
    from grid
    left join classified c
      on c.bucket_start = grid.bucket_start
     and c.flight_direction = grid.flight_direction
    group by grid.bucket_start, grid.flight_direction
    order by grid.bucket_start, grid.flight_direction;
$$;

revoke all on function public.airport_delay_analysis_hourly(text, timestamptz, integer)
from public, anon, authenticated;

grant execute on function public.airport_delay_analysis_hourly(text, timestamptz, integer)
to service_role;
