# Devices and groups

## Devices

`findplus devices` lists every tracker visible on your account and lets you
choose which ones to track (`--track <id>`, `--track-all`, `--untrack <id>`).
Only tracked devices are polled and shown on the dashboard. Untracking a
device stops polling it but keeps its history.

Each device gets its own coloured track on the map and its own row in the
sidebar. Timelines are never merged across devices: distance and elapsed
time between two points are only meaningful within a single tracker.

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
