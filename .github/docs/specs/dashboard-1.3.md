# Dashboard 1.3: Latest, People, All Activity

Status: approved direction from the owner (2026-10-05). Builders follow this file; anything it does not
say keeps today's behaviour.

## Why
The dashboard buries people (they only appear under "Groups"), spends a third of the screen on four status
cards and a filter row, has two levels of tabs (Dashboard/Places/Groups/Alerts, then Day story/Every sighting),
and every action is the same plain grey or blue text button. Colours and icons for people exist in the person
editor but almost nobody finds them.

## Owner asks (verbatim intent)
1. Better buttons for settings, grouping trackers, colours/icons, adding/editing/removing places.
2. The default side panel is **Latest**, **People**, **All Activity** instead of Day story / Every sighting.
3. A way to click a person or an individual tracker and see just them.
4. Assign colours (and icons) to people.

## Layout
- **App bar** (one row): Find+ mark, the status sentence ("17 trackers · checked every 5 min"), then actions
  as icon+label buttons: **Poll now** (refresh icon), **Add** (primary, plus icon; menu: Place, Person, Group),
  **Devices** (tag icon), **Settings** (gear icon). "Latest Location" moves into the map as a map control
  ("Fit to latest", crosshair icon) with the same behaviour.
- **Status cards** stay (their honesty text is test-pinned) but become a compact strip: four cells in one
  row, smaller type, the explainer disclosure kept. Do not change any honesty string.
- **Filter row** stays one row (Show, Group, Day arrows, Movement only, Export), visually lighter.
- **Side panel tabs** (one row, replaces the old tab row and the Day story/Every sighting switch at panel
  level): `Latest` (default) · `People` · `Activity` · `Places` · `Alerts`. "Groups" is no longer a tab:
  non-person groups live in the People tab under "Other groups". The last chosen tab is remembered per viewer
  (try/catch localStorage, key `findplus.panelTab`); deep links `#/latest`, `#/people`, `#/activity`,
  `#/places`, `#/alerts` select a tab; the old `#/groups` maps to `#/people`.

## Button system (shell owns it; everyone uses it)
- Classes in `web/components.css`: `.fp-btn` base; variants `.fp-btn--primary`, `.fp-btn--secondary`,
  `.fp-btn--ghost`, `.fp-btn--danger`; sizes `.fp-btn--sm`; `.fp-btn--icon` (icon only, needs aria-label).
  Visible focus ring, 32 px min height (24 px for sm), disabled state, dark theme.
- Helper `web/app/components/button.js`: `button({label, icon, variant, size, title, onClick})` returns a
  `<button type="button">` with an inline sprite icon (`icon_sprite.js` / `icons.svg`) and text. Icons are
  decorative (`aria-hidden`) when there is a label.
- Use it for: Add place, Edit, Delete, Notify me, Add group, Add person, Edit person, Full map, Send today's
  summary, Poll now, Settings, Devices, Show all/Hide all. Delete is always `--danger` and still confirms.

## Latest (default tab)
One list, people first (alphabetical), then trackers that belong to no person (most recent first):
- Person row: avatar (person icon on person colour; letter badge fallback), name, the existing one-line
  "where" sentence from the person engine (e.g. "Probably at Home, seen 19 min ago (keys)"), a confidence
  pill, and a small row of the person's tracker badges. Stale people are dimmed (stale ≠ home wording stays).
- Tracker row: tracker badge (its own icon/colour), label or name, where (place name if inside a place, else
  "Not at a saved place"), "seen 7 min ago" or "no recent sighting".
- Row click → focus (below). Each row has an Edit icon button (person editor / device label editor).
- Empty state: "No trackers yet" with the existing setup link.

## Focus
- Clicking a **tracker** (Latest row, Activity line, map marker popup "Show only this") focuses it in the side
  panel: header (back "All" button, badge, name, Edit), then a two-way switch **Story | Sightings** that shows
  today's Day story and Every sighting views for that one tracker (reuse trips_view / timeline as they are),
  and the map shows only that tracker. Back restores the previous tab and map. URL `#/tracker/<device_id>`.
- Clicking a **person** opens the existing person page (`#/person/<id>`), which keeps its story, date bar and
  map. Its header avatar is a button that opens the person editor on the icon/colour fields.

## All Activity
A merged, newest-first feed for the selected day across the trackers the Show/Group filters allow: one line
per sighting ("5:12 AM · Ali Keys · Home · ±100 m · rough fix"), with the tracker badge and, when the tracker
belongs to a person, the person's colour dot and name. Place arrivals/departures for people (existing
group_place_events) appear as their own lines ("Zaid arrived at School"). Suspect sightings keep their faint
style and note. Line click → tracker focus with that sighting highlighted. Paged: first 200 lines, then
"Show more". Day arrows from the filter row drive it.

## People tab
- "People" section: one card per person (existing groups_person_card, enriched): avatar (clickable → editor
  on icon/colour), name, where sentence, tracker badges, left-behind chips, buttons **Open**, **Edit**,
  **Delete**. Header buttons **Add person** and, when suggestions exist, the suggestions card ("Find+ found 2
  people in your trackers" with Review), moved here from the dashboard.
- "Other groups" section: today's non-person groups list with **Add group**, Edit, Delete.
- Pets use the same cards with the pet wording the engine already has.

## Colours and icons for people
- The person editor already has icon and colour pickers; make them reachable from every person avatar and
  the Edit buttons above. A new person gets a distinct colour from the 12-colour palette (first unused).
- Person colour shows on: the avatar everywhere, the Latest row, Activity lines (dot), the person page
  header, and as a ring around the map markers of the person's trackers on the dashboard map (tracker badge
  colour inside, person colour ring outside). No change to tracker colours themselves.

## Places
Places tab keeps its content; buttons move to the button system: **Add place** primary at the top, each place
card gets Edit (secondary) and Delete (danger) with icons, "Set up an alert" secondary. The App bar **Add →
Place** opens the same dialog.

## Non-goals
No change to the API contract except reads the panes need (prefer existing endpoints). No change to honesty
text, alert logic, polling, or the person engine. No new dependencies. Desktop (Tauri) and widget untouched.

## Tests and gates
Every builder: headless Playwright tests for its pane (bundled Chromium, FINDPLUS_STATE_DIR private), update
the existing browser tests that click the old tab names or the Day story/Every sighting switch, a11y (axe)
stays green in light and dark at 375 and 1280 px, ≤300 lines/file, ≤50 lines/function, strings in
`web/locales/en.json` (own namespace) with `gen-honesty-json.py` regenerating `catalog-en.js`.
