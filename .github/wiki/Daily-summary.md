# Daily summary

A short, plain-words account of one person's day, built from the sightings of the trackers that
belong to them. Ask for it by name, pick a date, or have it sent to Telegram each evening.

```
Sam's day, Mon Sep 21

- Overnight at Home (shoes and bag)
- 7:40 AM left Home (shoes)
- 8:10 AM arrived at School (shoes)
- 10:05 to 10:45 AM at an unnamed spot, 2.1 km from Home (shoes)
- Bag stayed at School from 3:00 PM. (bag)
- 3:00 PM left School (shoes)
- At Home from 3:33 PM (shoes)

1 sighting looked wrong and was left out.

Alerts inherit the network's delay. An arrival or departure may be reported minutes to hours late.
Stays and trips are worked out from sparse, delayed sightings. Times are when a tag was seen, and
distances are approximate straight lines, not the road driven.
```

## What is in it

| Line | When it appears |
|---|---|
| Overnight at Home | The person was at a Home place at midnight, on a fresh sighting (or the sightings either side of the night both say Home). |
| No sightings until 7:12 AM | Otherwise: nothing placed them at Home at midnight. |
| 7:40 AM left Home, 8:10 AM arrived at School | The person's arrivals and departures (the same events that send alerts). |
| At Home from 3:33 PM | The last Home visit of the day. Earlier Home visits stay as separate arrive and leave lines. |
| 10:05 to 10:45 AM at an unnamed spot, 2.1 km from Home | The lead tracker stayed 15 minutes or more away from every saved place. |
| No sightings 11:00 AM to 1:30 PM. | Over 90 minutes with no sighting, unless both ends were at Home. |
| Bag stayed at School from 3:00 PM. | A tracker was left behind (never listed at a Home place). |
| Still at School (seen 3:58 PM) | Today only, and only when the latest sighting is fresh and inside a saved place. |
| Last seen near School at 3:58 PM; nothing since | Today, when the data is stale. Find+ never says "still at" on stale data. |

## How it stays honest

- Every line names the tracker that backs it, in brackets, and the API lists the tracker ids
  (`evidence`) and a `confidence`.
- A time reads "around 7:40 AM" when the sightings that bound it are more than 10 minutes apart.
- Sightings that look wrong are left out; the footer counts them. Raw history is never changed.
- A tracker left behind never counts as the person's own sightings, and never leads the day.
- Days follow the local calendar day, including the 23 and 25 hour days when clocks change.
- The word "just" is not used here. A time is when a tag was seen.

## In the terminal

```
findplus day Sam                        # today
findplus day Sam --date 2026-09-21      # one day
findplus day Sam --days 3 --json        # three days, as a list
findplus day Sam --send                 # also send it to Telegram now
```

A name can be a unique start ("Za") or the person's id. `--timezone` takes an IANA zone; the
default is this computer's.

## Telegram evening summary

Off until you turn it on. Setting `people.digest`:

| Key | Default | Meaning |
|---|---|---|
| `enabled` | false | Send the summary. |
| `time` | "20:00" | Local time, 24-hour. |
| `people` | [] | Person ids. Empty means every person and pet. |
| `channel` | "auto" | Telegram, the only channel that carries it today. |
| `always_send` | false | Also send "No sightings for Sam on this day." |

```
findplus people digest --on --time 19:30 --person Sam --person Jamie
findplus people digest --all-people
findplus people digest --off
```

Or `PATCH /api/settings` with `{"people.digest": {"enabled": true, "time": "19:30"}}`.

- One message per person, per Telegram chat, per day. A restart or a second check never sends it
  twice (one `digest_runs` row per person, date, channel and chat).
- A failed send is tried once more a minute later, then logged as failed.
- A day with nothing tracked sends nothing, unless `always_send` is on.
- While the app lock is on and nobody has unlocked it, the summary is held, not dropped: it sends
  after the next unlock, if it is still the same day. Notifications are held while Find+ is locked.
- The message is a plain list with the person's name as the heading, and the delay and
  approximate-times sentences once at the end.

"Send today's summary" (`POST /api/people/{id}/day/send`) sends right now and never uses up the
evening one. It answers 409 when no Telegram chat is connected.

## For developers

`GET /api/people/{id}/day?date=YYYY-MM-DD&timezone=Area/City` returns the person, date, zone, the
`now` answer (today only), `lines[]`, `left_behind[]`, `suspect_count`, `gaps[]`, `trackers[]` and
the `label` sentence. See the [API reference](API-reference). The algorithm is
`cli/src/findplus/people/day.py`; it is pure, so it is tested on named synthetic days.

---
[[Home]]
