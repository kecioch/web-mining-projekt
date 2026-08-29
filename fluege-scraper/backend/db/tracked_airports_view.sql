create or replace view public.tracked_airports as
select a.icao,
       a.name,
       a.iata,
       a.latitude,
       a.longitude,
       a.website_url
from public.airports a
where exists (
        select 1 from public.arrivals ar where ar.airport_icao = a.icao
      )
   or exists (
        select 1 from public.departures d where d.airport_icao = a.icao
      );
