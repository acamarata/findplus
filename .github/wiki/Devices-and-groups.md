# Devices and groups

## Devices

`findplus devices` lists every tracker visible on your account and lets you
choose which ones to track (`--track <id>`, `--track-all`, `--untrack <id>`).
Only tracked devices are polled and shown on the dashboard. Untracking a
device stops polling it but keeps its history.

Each device gets its own colored track on the map and its own row in the
sidebar. Timelines are never merged across devices: distance and elapsed
time between two points are only meaningful within a single tracker.

## Labels, icons and colors

Every device carries three things you choose: a label, an icon, and a color.
Together they make the badge you see on the map, on the timeline track heads,
on the device list, and in the macOS widget.

**Label.** Free text, up to 40 characters. A label is local only: it is never
sent to Google or Apple, and a provider name refresh never overwrites one you
have set. Clear the field to go back to the provider's own name.

**Icon.** One of five forms:

| Form | What it shows |
|---|---|
| `lucide:<name>` | One of the 49 bundled Lucide glyphs. |
| `letter:<A-Z0-9>` | A badge character you pin once, which never changes. |
| `letter` | A badge character computed live from the current label or name. |
| `none` | A plain colored dot with no glyph. |
| `custom:<id>` | A PNG image you uploaded. |

Bare `letter` is the default and is dynamic: it always shows the first
character of the name in force right now, so renaming a device moves its badge
letter with it. `letter:X` is the opposite, and stays on X whatever the device
is called.

The 49 glyphs come from Lucide 0.462.0 and are bundled with Find+, so the
dashboard never fetches an icon from anywhere. The picker groups them as
people (9), pets (8), things (22) and places (10). `footprints` sits in the
things group, where it is the picker's only footwear-adjacent glyph.

Forty-nine glyphs will not cover every label anyone writes, and that is fine:
the colored letter badge covers any label with no matching glyph, so the
picker never has a dead end. Run `findplus devices icons` to print every
available id.

**Custom icons.** The picker's "Your icons" section lets you upload your own
PNG (16-512 px, roughly square, up to 64 KiB) instead of picking a Lucide
glyph or a letter. Each upload gets an id derived from its own bytes, so
uploading the same image twice reuses the first copy rather than storing it
twice. An icon still assigned to a device or group cannot be deleted. Remove
it from whatever is using it first. The macOS widget cannot fetch images, so
a custom icon shows there as a colored letter badge instead, the same
fallback an unmapped Lucide glyph would get.

**Color.** One of 12 palette swatches, or any hex color you pick. A device
that has never been given one gets a palette color derived from its id, so two
devices rarely start out the same color.

```bash
findplus devices label <ID> --label "Mom" --icon lucide:user-round --color "#4f8cf7"
findplus devices icons
```

From the dashboard, every row in the Devices dialog has an **Edit** button with
the same three controls.

## Groups

A group is a named set of devices with a quorum rule:

| Quorum | Meaning |
|---|---|
| `any` | Group presence follows the single closest member. |
| `majority` | More than half the members must agree. |
| `all` | Every member must agree. |
| `N` | At least N members must agree. |

`cluster_radius_meters` sets how close members must be to count as
together. `stale_after` (minutes) sets how long a fix stays valid before the
device is treated as unknown for presence purposes.

A group also carries an icon and a color, set in the group dialog beside the
quorum rule. The icon defaults to `lucide:users` and follows the same
five-form grammar devices use, custom icons included. It is what you see on
the group card and in the map legend.

## Presence verdicts

| Verdict | Meaning |
|---|---|
| `TOGETHER` | Enough members are within the cluster radius of each other. |
| `APART` | Members are tracked and fresh, but not clustered. |
| `PARTIAL` | Some members are stale or missing a recent fix. |
| `UNKNOWN` | No member has a fix recent enough to evaluate. |

`findplus groups presence` prints the live verdict, a note, and a per-device
table. `findplus groups events` lists confirmed group ENTER/EXIT crossings
at a place.

A tag with no recent fix is stale, not at home and not left behind. Find+
reports it as unknown.

---
[[Home]]
