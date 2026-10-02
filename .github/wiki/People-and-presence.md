# People and presence

A person (or a pet) is a group of trackers that belong to one someone: Sam's bag, bike and two
pairs of shoes. Find+ works out where the person probably is from the trackers that are actually
being carried, sends one alert when the person arrives or leaves a place, and notices when a
tracker was left behind.

## Suggestions from tracker names

Find+ reads your tracker names and suggests people. Nothing is grouped until you accept.

| Names | Suggestion |
|---|---|
| Sam Bag, Sam Bike, Sam Shoes Red, Sam Shoes White | Person "Sam": bag, bike, shoes, shoes |
| Ali Pixel 8a, Ali Keys | Person "Ali": phone, keys |
| Whiskers | "Is Whiskers a person or a pet?" (suggested as a pet) |
| Pixel 11 Pro | No owner in the name: listed under "Whose is this?" |
| Rose Bag | Suggested, but flagged: Rose is also a colour |

Owner names match exactly, so "Ali" and "Alia" stay apart. A tracker already in a person is never
moved. A group with the same name is offered as "Turn group Sam into a person". When a new tracker
appears ("Sam Helmet"), Find+ asks whether to add it. A dismissed suggestion stays dismissed.

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

A tracker that moved was carried, for 45 minutes after its last move. A tracker that has sat
still since then is neutral, and one still for six hours proves little. Find+
scores each tracker by its weight, how recent its sighting is, whether it moved, and how accurate
it is, then groups the trackers that are close together. The answer is always in plain words:

- **Likely at School, seen 12 min ago (shoes, bike).**
- **Probably near Home** when the evidence is thinner, for example only the bag reported.
- **Not sure: shoes near School, bag near Home.** when the trackers disagree. "Not sure" never
  sends an alert.
- **No recent sightings. Last seen near Home at 4:10 PM.** when nothing has reported recently.

A tag with no recent fix is stale, not at home and not left behind. Find+ reports it as unknown.
Trackers that never moved cannot move the person: if Sam's shoes go quiet at School while his bag
and bike keep reporting from Home, Sam stays "at School" and the shoes read "no recent sighting".
When the trackers left sitting disagree with one that moved later, the answer is "Not sure".

The person's position is always one tracker's own sighting. Tracks are never merged across
trackers and no point is invented.

## Arrived and left

When the person crosses a place, Find+ sends one message, however many of their trackers crossed:

```
Sam just arrived at Grandma's
Seen by Sam Shoes Red · reported Sep 26, 4:31 PM EDT · 2 min late
Alerts inherit the network's delay. An arrival or departure may be reported minutes to hours late.
```

"Just" is used only when the sighting is under 10 minutes old when the message is sent; otherwise
the message gives the time ("Sam left Home at Sep 26, 7:40 AM EDT"). When a tracker stays behind,
the message says so ("Sam's bag stayed at Home."), and a weaker answer says "(probably; only the
bag reported)"; that note is never cut from a long message. Leaving waits for the tracker's own
second sighting outside, so one stray fix never sends "left", and the time given is the first
sighting outside. A person who flips back across the same place waits 10 minutes before the
opposite event, a late, older report never rewrites what already happened, and a sighting dated
after it was fetched (a reporter with a fast clock) is ignored.

Every new place gets a rule "Arrivals and departures at <place>" for everyone, on the channel you
use: Telegram if it is the only one connected (or one of several), otherwise WhatsApp or the
webhook, otherwise macOS notifications once the desktop app has shown one. With nothing connected
the rule is saved turned off with the hint "Connect Telegram to get these." Creating a place with
`"notify": false` skips it. For places you already have, `POST /api/places/notify-defaults` adds
the same rule; with `?dry_run=1` it only lists what it would add.

An everyone rule, or a rule for one person, replaces the per-tracker alerts for that person's
trackers at the same place, but only when Find+ recorded that person's own crossing; otherwise the
tracker's rule still sends. One crossing is one message per chat, however many rules match it. A
new place gets no rule of its own when an everyone rule for every place already covers it.
Everyone rules cover people, not pets: a pet alerts only through a rule that names it.

Places you made before 1.1.6 get a kind from their name on upgrade ("Home" becomes home). The
Places list shows it as a guess with a one-tap "That's right".

## Left behind

If Sam's shoes go home while his bag stays at School for 20 minutes, and Sam is seen away from it
twice (or once after the bag's last report), Find+ sends once: "Sam's bag looks left at School.
Last seen there at 3:02 PM." Only Sam's own sightings count, never the bike in the garage. A quiet
tag (Find Hub tags that sit still report about every one to two hours) is not taken as carried:
the episode waits for news. A bag that goes quiet and reports again is the same episode.
Left-behind alerts follow one setting, "Tell me when a tracker looks left behind", and work
anywhere, including a spot with no saved place; they use the channels of any rule that covers the
person, whatever its place. With no such rule the episode waits, unsent, until one exists. It does
not alert at a Home place (a bike in the garage is normal), pets only alert through a rule naming
them, and you can turn left-behind alerts off entirely (`PUT /api/people/settings`). The episode ends when the bag moves, when Sam comes back for it, or
when the bag stops reporting (shown as "no recent sighting", never "still left behind"). "I know"
silences that tracker at that place for the rest of the day.

## The Person page

Click a person's name on a group card, in an alert rule, in the delivery log or in the arrivals
list. The address is `#/person/<id>?date=YYYY-MM-DD`, so the Back button steps through days.

- The header says where the person probably is, how sure Find+ is (likely, probably, not sure, no
  recent sighting) and how long ago anything was seen.
- The day bar has previous and next arrows, a date picker, Today, and the left and right arrow
  keys. Nothing can be picked after today.
- The day summary lists the lines for the day ("7:40 AM left Home"). Select a line to move the
  map and the day story to that moment. Each line says which trackers it rests on.
- The map draws one line per tracker. Trackers are never joined into one path. Sightings that look
  wrong are drawn faintly in a dashed ring; the "Show sightings that look wrong" box turns them off.
- The day story reuses the dashboard's lanes (best sighting first) and the list of stays and trips.
- Each tracker shows its role, its weight and what it did that day (carried, left at School, moved
  without Sam, no recent sighting). Edit changes the role or the weight.
- Send today's summary posts the day to your Telegram chat and says where it went, or why it did
  not. Notify me opens a rule for this person. Edit person opens the group editor. Full map shows
  the group on the dashboard map.
- Loading, a day with no sightings, a partly loaded day, an error with Retry, no connection, and a
  locked app each have their own words. Locking removes every name, time and place from the page.

The suggestions panel ("We found people in your trackers") lives on the Groups tab, as a one-line
banner on the dashboard, and in the setup wizard's Groups step. It has Accept all (it skips guesses
that still need an answer or are low confidence) and Check again.

## The day in plain words

Click a person to see their day, or ask for it: `findplus day Sam`, `GET /api/people/{id}/day`,
or the MCP tool `get_person_day`. It reads like "7:40 AM left Home / 8:10 AM arrived at School /
3:00 PM left School / At Home from 3:33 PM". Details, the Telegram evening summary and the wording
rules are on [Daily summary](Daily-summary).

## Known limits

- A sibling wearing Sam's shoes looks exactly like Sam. Every message names the tracker it rests
  on, so you can tell.
- A bag moving on its own (someone else carried it) is "not sure", not "Sam left".
- Alerts are only as fresh as the network's sightings.

---
[[Home]]
