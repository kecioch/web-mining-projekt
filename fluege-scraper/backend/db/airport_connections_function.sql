create or replace function public.airport_connections(
    p_icao text,
    p_from timestamptz default null
)
returns table (
    direction text,
    connection_icao text,
    connection_name text,
    connection_iata text,
    connection_latitude double precision,
    connection_longitude double precision,
    connection_website_url text,
    flight_count bigint
)
language sql
stable
as $$
    select 'departure'::text as direction,
           d.destination_icao as connection_icao,
           a.name  as connection_name,
           a.iata  as connection_iata,
           a.latitude  as connection_latitude,
           a.longitude as connection_longitude,
           a.website_url as connection_website_url,
           count(*) as flight_count
    from public.departures d
    left join public.airports a on a.icao = d.destination_icao
    where d.airport_icao = p_icao
      and d.destination_icao is not null
      and (p_from is null or coalesce(d.scheduled_departure_at, d.scraped_at) >= p_from)
    group by d.destination_icao, a.name, a.iata, a.latitude, a.longitude, a.website_url

    union all

    select 'arrival'::text as direction,
           ar.origin_icao as connection_icao,
           a.name  as connection_name,
           a.iata  as connection_iata,
           a.latitude  as connection_latitude,
           a.longitude as connection_longitude,
           a.website_url as connection_website_url,
           count(*) as flight_count
    from public.arrivals ar
    left join public.airports a on a.icao = ar.origin_icao
    where ar.airport_icao = p_icao
      and ar.origin_icao is not null
      and (p_from is null or coalesce(ar.scheduled_arrival_at, ar.scraped_at) >= p_from)
    group by ar.origin_icao, a.name, a.iata, a.latitude, a.longitude, a.website_url;
$$;
