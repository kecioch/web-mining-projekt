-- Einmalig im Supabase SQL Editor ausführen.
-- Die Funktion liest ausschließlich den neuesten vorhandenen Rohdatenzeitpunkt.

create or replace function public.airport_latest_movement_at(
    p_icao text
)
returns timestamptz
language sql
stable
set search_path = public
as $$
    select max(movement_at)
    from (
        select coalesce(d.scheduled_departure_at, d.scraped_at) as movement_at
        from public.departures d
        where d.airport_icao = upper(p_icao)

        union all

        select coalesce(ar.scheduled_arrival_at, ar.scraped_at) as movement_at
        from public.arrivals ar
        where ar.airport_icao = upper(p_icao)
    ) movements;
$$;

revoke all on function public.airport_latest_movement_at(text)
from public, anon, authenticated;

grant execute on function public.airport_latest_movement_at(text)
to service_role;
