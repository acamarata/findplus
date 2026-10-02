# People and presence

A person (or a pet) is a group of trackers that belong to one someone: Zaid's bag, bike and two
pairs of shoes. Find+ works out where the person probably is from the trackers that are actually
being carried, sends one alert when the person arrives or leaves a place, and notices when a
tracker was left behind.

## Suggestions from tracker names

Find+ reads your tracker names and suggests people. Nothing is grouped until you accept.

| Names | Suggestion |
|---|---|
| Zaid Bag, Zaid Bike, Zaid Shoes Red, Zaid Shoes White | Person "Zaid": bag, bike, shoes, shoes |
| Ali Pixel 8a, Ali Keys | Person "Ali": phone, keys |
| Meong | "Is Meong a person or a pet?" (suggested as a pet) |
| Pixel 11 Pro | No owner in the name: listed under "Whose is this?" |
| Rose Bag | Suggested, but flagged: Rose is also a colour |

Owner names match exactly, so "Ali" and "Alia" stay apart. A tracker already in a person is never
moved. A group with the same name is offered as "Turn group Zaid into a person". When a new tracker
appears ("Zaid Helmet"), Find+ asks whether to add it. A dismissed suggestion stays dismissed.

From the terminal:

```
findplus people suggest
findplus people accept --key <key>     # or --all
findplus people set-role <device_id> bag --weight 0.5
findplus people list
```

The API is `GET /api/people/suggestions` (a preview, saves nothing) and
`POST /api/people/suggestions/accept`. See the [API reference](API-reference).

## Roles and carry weights

Each tracker has a role, guessed from its name, and a carry weight: how much its position says
about where the person is.

| Role | Weight |
|---|---|
| phone, watch, collar | 1.0 |
| wallet, keys, shoes | 0.8 |
| bag, jacket, other | 0.5 |
| bike, scooter, tablet, laptop | 0.4 |
| car, luggage | 0.2 |

These numbers are judgement calls. Change any tracker's role or weight (0 means "never use this
tracker to place the person").

## Where is the person now

A tracker that moved was carried. A tracker that has sat still for six hours proves little. Find+
scores each tracker by its weight, how recent its sighting is, whether it moved, and how accurate
it is, then groups the trackers that are close together. The answer is always in plain words:

- **Likely at School, seen 12 min ago (shoes, bike).**
- **Probably near Home** when the evidence is thinner, for example only the bag reported.
- **Not sure: shoes near School, bag near Home.** when the trackers disagree. "Not sure" never
  sends an alert.
- **No recent sightings. Last seen near Home at 4:10 PM.** when nothing has reported recently.

A tag with no recent fix is stale, not at home and not left behind. Find+ reports it as unknown.

The person's position is always one tracker's own sighting. Tracks are never merged across
trackers and no point is invented.

## Arrived and left

When the person crosses a place, Find+ sends one message, however many of their trackers crossed:

```
Zaid just arrived at Grandma's
Seen by Zaid Shoes Red · reported Sep 26, 4:31 PM EDT · 2 min late
Alerts inherit the network's delay. An arrival or departure may be reported minutes to hours late.
```

"Just" is used only when the sighting is under 10 minutes old when the message is sent; otherwise
the message gives the time ("Zaid left Home at Sep 26, 7:40 AM EDT"). When a tracker stays behind,
the message says so ("Zaid's bag stayed at Home."), and a weaker answer says "(probably; only the
bag reported)". A person who flips back across the same place waits 10 minutes before the opposite
event, and a late, older report never rewrites what already happened.

Every new place gets a rule "Arrivals and departures at <place>" for everyone, on the channel you
use: Telegram if it is the only one connected (or one of several), otherwise WhatsApp or the
webhook, otherwise macOS notifications once the desktop app has shown one. With nothing connected
the rule is saved turned off with the hint "Connect Telegram to get these." Creating a place with
`"notify": false` skips it. For places you already have, `POST /api/places/notify-defaults` adds
the same rule; with `?dry_run=1` it only lists what it would add.

An everyone rule, or a rule for one person, replaces the per-tracker alerts for that person's
trackers at the same place, so one crossing is one message.

## Left behind

If Zaid's shoes go home while his bag stays at School for 20 minutes and two more sightings, Find+
sends once: "Zaid's bag looks left at School. Last seen there at 3:02 PM." It does not alert at a
Home place (a bike in the garage is normal), and you can turn left-behind alerts off entirely
(`PUT /api/people/settings`). The episode ends when the bag moves, when Zaid comes back for it, or
when the bag stops reporting (shown as "no recent sighting", never "still left behind"). "I know"
silences that tracker at that place for the rest of the day.

## The day in plain words

Click a person to see their day, or ask for it: `findplus day Zaid`, `GET /api/people/{id}/day`,
or the MCP tool `get_person_day`. It reads like "7:40 AM left Home / 8:10 AM arrived at School /
3:00 PM left School / At Home from 3:33 PM". Details, the Telegram evening summary and the wording
rules are on [Daily summary](Daily-summary).

## Known limits

- A sibling wearing Zaid's shoes looks exactly like Zaid. Every message names the tracker it rests
  on, so you can tell.
- A bag moving on its own (someone else carried it) is "not sure", not "Zaid left".
- Alerts are only as fresh as the network's sightings.

---
[[Home]]
