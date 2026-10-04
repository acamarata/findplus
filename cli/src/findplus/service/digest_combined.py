"""The evening summary as one family message per chat (uat116 #13).

Purpose    : Eight people meant eight Telegram messages at once, each with the
             same long honesty footer. With `people.digest.combined` (default
             on) each chat gets one message: a heading, each person's name and
             lines, the footer once (people/day_render.render_combined).
Inputs     : The DigestScheduler (its claim/record/finish bookkeeping and its
             pending-target query), the people, the preference, the Telegram
             credentials, the local day, zone and `now`.
Outputs    : One Outcome per (person, target), exactly like the per-person path.
Constraints: Still one digest_runs row per (person, day, channel, target), so a
             restart never resends and a person added later still gets a message
             of their own that evening. One chat's failure never stops another.
"""

from __future__ import annotations

from findplus.db.models import Group
from findplus.db.session import session_scope
from findplus.people.day_load import day_payload
from findplus.people.day_render import render_combined
from findplus.service.digest_send import send_to_targets


def _payloads(sched, ids, prefs, creds, day, tz, now, retry_only=False):
    """(pending targets per person, payloads to send, outcomes of skipped people)."""
    pending, payloads, skipped = {}, {}, []
    for group_id in ids:
        targets = sched._pending_targets(group_id, day, creds, now, retry_only)
        if not targets:
            continue
        with session_scope() as s:
            group = s.get(Group, group_id)
            payload = day_payload(s, group, day, tz, now) if group is not None else None
        if payload is None:
            continue
        if payload["empty"] and not prefs["always_send"]:
            skipped += [sched._record(group_id, day, t, "skipped", now, "nothing tracked")
                        for t in targets]  # fmt: skip
            continue
        pending[group_id], payloads[group_id] = targets, payload
    return pending, payloads, skipped


def run_combined(sched, ids: list[int], prefs, creds, day, tz, now, retry_only=False) -> list:
    """Send one message per chat covering every person still due there."""
    pending, payloads, out = _payloads(sched, ids, prefs, creds, day, tz, now, retry_only)
    for chat in creds.chat_ids:
        people = [g for g in ids if chat in pending.get(g, ())]
        if not people:
            continue
        text = render_combined([payloads[g] for g in people])
        for group_id in people:
            sched._claim(group_id, day, chat, now)
        (result,) = send_to_targets(text, creds, sched._sender, [chat])
        out += [sched._finish(group_id, day, result, now) for group_id in people]
    return out
