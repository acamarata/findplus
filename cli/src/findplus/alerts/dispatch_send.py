"""Channel selection and outcome classification for one alert.

Purpose    : Split out of dispatch.py so both stay under the 300-line cap
             (PRI rule 7) once CF-14 made the delivery row carry a real
             status. dispatch.py owns the transaction and the dedup; this
             module owns "which channel, and did it work".
Inputs     : A Rule, the event it matched, the channel config.
Outputs    : _send -> a channel SendResult or None (channel unconfigured);
             _status_for -> the (status, error) pair written to the row.
Constraints: Never raises. A channel failure must not crash dispatch or the
             poller, so _status_for converts every exception into a row.
"""

from __future__ import annotations

import datetime

from findplus.alerts.dispatch_core import (
    DeviceEvent,
    GroupEvent,
    Rule,
    as_utc,
    render_message,
)


def _send(rule: Rule, event: DeviceEvent | GroupEvent, kind: str, text_msg: str, channels_cfg):
    from findplus.alerts.channels.telegram import send as tg_send
    from findplus.alerts.channels.webhook import build_payload, send_webhook

    if rule.channel == "telegram" and channels_cfg.telegram:
        return tg_send(text_msg, channels_cfg.telegram.bot_token, channels_cfg.telegram.chat_id)
    if rule.channel == "webhook" and channels_cfg.webhook:
        subject_id = event.device_id if isinstance(event, DeviceEvent) else event.group_id
        subject_name = event.device_name if isinstance(event, DeviceEvent) else event.group_name
        observed_at = as_utc(event.observed_at)
        fetched_at = as_utc(getattr(event, "fetched_at", None))
        lag = round((fetched_at - observed_at).total_seconds() / 60) if fetched_at else None
        payload = build_payload(
            event.event_type,
            kind,
            subject_id,
            subject_name,
            event.place_id,
            event.place_name,
            observed_at,
            fetched_at,
            lag,
            event.confidence or "",
            getattr(event, "note", ""),
        )
        return send_webhook(payload, channels_cfg.webhook.url, channels_cfg.webhook.secret)
    return None


def _status_for(
    rule: Rule, event, kind: str, channels_cfg, now: datetime.datetime
) -> tuple[str, str | None]:
    """Send one alert and classify the outcome as (status, error) for the row."""
    try:
        text_msg = render_message(event, now)
        result = _send(rule, event, kind, text_msg, channels_cfg)
    except Exception as exc:  # a channel failure must never crash dispatch/the poller
        return "failed", str(exc)[:500]
    if result is None:
        # The rule names a channel that has no credentials — a telegram rule
        # created before telegram-setup finished, or one left enabled after
        # DELETE /api/alerts/channels/telegram, which does not touch rules.
        # This used to return before writing anything while process() still
        # stamped notified_at, so the event was swallowed for good and never
        # appeared in GET /api/alerts/deliveries. Record it instead; the
        # cooldown filter keys on status == "sent", so this starts none.
        return "skipped", f"{rule.channel} is not configured"
    return ("sent" if result.success else "failed"), result.error
