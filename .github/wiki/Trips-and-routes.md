# Trips and routes

Find Hub sightings arrive every few minutes to hours, with an accuracy of
roughly 50 to 200 metres. A tag sitting at home can report ten times in a row
from slightly different spots. Find+ turns that raw stream into something a
person can read: where the tag stayed, when it travelled, and where nothing was
seen.

> Stays and trips are worked out from sparse, delayed sightings. Times are when a tag
> was seen, and distances are approximate straight lines, not the road driven.

## What you get

- **Stays.** Consecutive sightings inside one circle for at least 10 minutes become one
  row with a fix count. The circle is the larger of 75 m and 1.5 times the sighting's own
  accuracy, measured from a running centre, so jitter inside the accuracy circle never
  starts a trip. A stay inside a saved place carries its name ("Home"); any other is an
  "Unnamed stop".
- **Trips.** The movement between two stays: start and end time and place, duration, an
  approximate straight-line distance, the number of sightings and the longest gap.
- **Gaps.** "No sightings between 3:10 and 4:40." Shown whenever two sightings are more
  than 60 minutes apart (change it with `gap_minutes`). A gap is missing data, not proof
  the tag stayed put.
- **Strays.** A single sighting that would need an impossible speed (over about 200 km/h)
  from both neighbours is left out of trips. It stays in your history and is listed
  under `outliers`.

## Ask for it

```
findplus trips --date 2026-09-18            # table, one tracked device
findplus trips --device-id ID --days 3 --json
curl 'http://localhost:8647/api/trips?device_id=ID&date=2026-09-18'
```

The MCP server exposes the same answer as `get_trips`. Each device is segmented on its
own; devices are never merged. A locked app refuses the route like every other data route.

## Likely route along roads (optional)

Off by default. Nothing is sent anywhere unless you set `routing.endpoint` to the base
URL of an OSRM-compatible server, for example your own OSRM or Valhalla-OSRM instance.
Find+ never ships a public demo server address.

> Road routes are off unless you enter a routing server address. When one is set, the
> sightings of each trip you open are sent to that server to draw the path, so use a
> server you run yourself.

Set it with `POST /api/settings/routing.endpoint` and `{"value": "http://127.0.0.1:5000"}`;
an empty value turns it off. `GET /api/trips/route?device_id=ID&trip_id=T` then asks the
server's `/match` service (falling back to `/route`) and returns a GeoJSON LineString:

> Likely route between sparse sightings, not a record of the road driven.

If the server is unreachable, refuses, or finds no road, you get straight dashed segments
between the sightings instead. At most 60 sightings are sent per trip.
