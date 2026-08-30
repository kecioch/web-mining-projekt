create or replace function public.airport_airlines(
    p_icao text,
    p_from timestamptz default null
)
returns table (
    airline_icao text,
    airline_name text,
    airline_iata text,
    flight_count bigint
)
language sql
stable
as $$
    with movements as (
        select d.airline_icao
        from public.departures d
        where d.airport_icao = p_icao
          and d.airline_icao is not null
          and (p_from is null or coalesce(d.scheduled_departure_at, d.scraped_at) >= p_from)

        union all

        select ar.airline_icao
        from public.arrivals ar
        where ar.airport_icao = p_icao
          and ar.airline_icao is not null
          and (p_from is null or coalesce(ar.scheduled_arrival_at, ar.scraped_at) >= p_from)
    )
    select m.airline_icao,
           al.name as airline_name,
           al.iata as airline_iata,
           count(*) as flight_count
    from movements m
    left join public.airlines al on al.icao = m.airline_icao
    group by m.airline_icao, al.name, al.iata
    order by flight_count desc;
$$;
