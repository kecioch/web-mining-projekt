create or replace function public.airport_aircraft(
    p_icao text,
    p_from timestamptz default null
)
returns table (
    aircraft_code text,
    aircraft_type text,
    flight_count bigint
)
language sql
stable
as $$
    with movements as (
        select d.aircraft_code
        from public.departures d
        where d.airport_icao = p_icao
          and d.aircraft_code is not null
          and (p_from is null or coalesce(d.scheduled_departure_at, d.scraped_at) >= p_from)

        union all

        select ar.aircraft_code
        from public.arrivals ar
        where ar.airport_icao = p_icao
          and ar.aircraft_code is not null
          and (p_from is null or coalesce(ar.scheduled_arrival_at, ar.scraped_at) >= p_from)
    )
    select m.aircraft_code,
           ac.type as aircraft_type,
           count(*) as flight_count
    from movements m
    left join public.aircraft ac on ac.code = m.aircraft_code
    group by m.aircraft_code, ac.type
    order by flight_count desc;
$$;
