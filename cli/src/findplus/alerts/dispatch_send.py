"""Channel selection and outcome classification for one alert.

Purpose    : Split out of dispatch.py so both stay under the 300-line cap
             (PRI rule 7) once CF-14 made the delivery row carry a real
             status. dispatch.py owns the transaction and the dedup; this
             module owns "which channel, and did it work".
Inputs     : The channel id, a Rule, the event it matched, the channel config.
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
from findplus.redaction import redact_text


def _send(
    channel: str,
    rule: Rule,
    event: DeviceEvent | GroupEvent,
    kind: str,
    text_msg: str,
    channels_cfg,
    target: str = "",
):
    from findplus.alerts.channels.telegram import send as tg_send
    from findplus.alerts.channels.webhook import build_payload, send_webhook

    if channel == "telegram" and channels_cfg.telegram:
        # `target` is one of channels_cfg.telegram.chat_ids -- dispatch.py's
        # _channel_targets() is the only caller that fans a telegram send out
        # over more than one target, one _send() call per target. The
        # chat_ids[0] fallback only matters for a caller that passes no
        # target at all (never dispatch.py itself, kept for callers outside
        # the per-target loop, e.g. a future direct _send() use).
        chat_id = target or (
            channels_cfg.telegram.chat_ids[0] if channels_cfg.telegram.chat_ids else None
        )
        if not chat_id:
            return None
        return tg_send(text_msg, channels_cfg.telegram.bot_token, chat_id)
    if channel == "webhook" and channels_cfg.webhook:
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
    if channel == "whatsapp" and getattr(channels_cfg, "whatsapp", None):
        from findplus.alerts.channels.whatsapp_callmebot import send as wa_send

        return wa_send(text_msg, channels_cfg.whatsapp.phone, channels_cfg.whatsapp.apikey)
    return None


def _status_for(
    channel: str,
    rule: Rule,
    event,
    kind: str,
    channels_cfg,
    now: datetime.datetime,
    target: str = "",
) -> tuple[str, str | None, int | None, int | None]:
    """Send one alert; classify the outcome as (status, error, status_code, retry_after).

    status_code and retry_after (seconds, from a 429's Retry-After header) are
    None whenever the channel raised, was unconfigured, or never carried
    either value -- dispatch.py's classify_new_delivery() treats a None
    status_code as non-retryable unless the error is exactly "timeout".

    `target` selects which of a multi-target channel's targets this call
    sends to (Telegram only today; every other channel ignores it). A retry
    (alerts/retry.py) passes the row's own stored `target` back in, so a
    retry always resends to the exact target that first failed.
    """
    try:
        text_msg = render_message(event, now)
        result = _send(channel, rule, event, kind, text_msg, channels_cfg, target)
    except Exception as exc:  # a channel failure must never crash dispatch/the poller
        return "failed", redact_text(str(exc)[:500]), None, None
    if result is None:
        # The rule names a channel that has no credentials — a telegram rule
        # created before telegram-setup finished, or one left enabled after
        # DELETE /api/alerts/channels/telegram, which does not touch rules.
        # This used to return before writing anything while process() still
        # stamped notified_at, so the event was swallowed for good and never
        # appeared in GET /api/alerts/deliveries. Record it instead; the
        # cooldown filter keys on status == "sent", so this starts none.
        return "skipped", f"{channel} is not configured", None, None
    # CF-14 displays this column, and httpx status errors carry the request URL
    # -- a webhook with its key in the query string would otherwise show it.
    status_code = getattr(result, "status_code", None)
    retry_after = getattr(result, "retry_after_seconds", None)
    status = "sent" if result.success else "failed"
    return status, redact_text(result.error), status_code, retry_after
