# FAQ

**Does it work without internet?**
Polling needs a network connection to query Google or Apple. The dashboard
itself, and everything already in the database, works offline.

**Is location data sent anywhere?**
No. Find+ queries Google's or Apple's own network for your tag's location
and stores the result locally in `~/.findplus/`. Nothing is sent to any
Find+ server, because there is no Find+ server.

**Does it work with AirTags?**
Only accessories whose keys you hold. Genuine AirTags require extracting
pairing keys from a device that has already paired with them, which most
users cannot do.

**What is Find Hub?**
Google's crowdsourced tracker network (formerly Find My Device), which
Moto Tag and compatible trackers use. Nearby Android devices relay a tag's
location back to its owner's account.

**Can I track multiple people or devices at once?**
Yes, using groups. A group of devices reports a combined presence verdict
(together, partial, or unknown) based on a configurable quorum rule.

**How do I uninstall?**
`findplus uninstall --yes` removes the service and watchdog unit files.
Remove `~/.findplus/` by hand if you also want to delete your history; that includes
`~/.findplus/backups/`.

**Why did Find+ say Sam left School?**
A person is placed by the trackers they actually carry. Find+ said it because a tracker of Sam's
that was moving reported a sighting outside School's circle, and the next one confirmed it. Open
Sam's page from the alert: it shows the tracker, the time and how sure Find+ is. Alerts inherit
Find Hub's delay, so the message can be late. If a one-off bad sighting caused it, the sighting
is greyed out and the alert is held back or never sent.

**What is a left-behind alert?**
"Sam's bag looks left at School" means the tracker on the bag has stayed put at a place while
Sam's other trackers moved away. It is a guess, sent once per episode, never for Home, and only
on rules for any place or that place. Tap "I know" on the dashboard to clear it.

**Why is a sighting greyed out?**
Find+ scored it as unlikely: it jumped far and came straight back, needed an impossible speed,
or disagreed with the person's other trackers. It is drawn faintly with a dashed ring and the
reason on hover. It stays in your history and exports, but not in stays, trips, distance or
alerts. The "Show sightings that look wrong" box hides or shows them. See
[[Trips-and-routes]].

**How do I restore a backup?**
Quit the Find+ app, then `findplus stop`, `findplus db backups` to list copies, and
`findplus db restore ~/.findplus/backups/<file>.sqlite`, then `findplus start`. Restore checks the
file, keeps the database it replaces, and refuses while Find+ runs. Backups are unencrypted
copies. See [[Backup-and-restore]].

**Is my daily summary sent anywhere?**
Only if you turn on the evening digest or press Send. It goes to the chat you pick on Telegram
and names people, places and times. See [[Privacy-and-threat-model]].

**What is the MCP server?**
An [MCP](https://modelcontextprotocol.io) endpoint (`findplus mcp`) that
lets an LLM client such as Claude Desktop or Claude Code query your
location history, places, and groups as tools.

**Is Find+ affiliated with Apple or Google?**
Find+ is not affiliated with Apple or Google. Find Hub and Find My are
their trademarks.

---
[[Home]]
