"""Multi-device group export: resolve members, stitch per-device tracks.

Purpose    : Shared by api/routes_history.py and cli/cmd_history.py so "one
             track per member, never merged" (PROMPT.md §2 invariant 5) is
             implemented exactly once instead of twice.
Inputs     : An open Session, a group id (possibly not a valid int), a UTC
             time range.
Outputs    : Member device_ids in stable (device name) order; rendered
             CSV/JSON/GPX/KML text spanning every member's observations.
Constraints: Reuses findplus.exporters' per-device formatters for CSV/JSON —
             this module only resolves membership and stitches per-device
             output together; it never re-derives observation fields itself.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from xml.sax.saxutils import escape

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from findplus.db.models import Device, DeviceGroup, Group, LocationObservation
from findplus.exporters import CSV_COMMENT, csv_table, to_csv, to_json
from findplus.timeline import fetch_observations


class GroupNotFoundError(Exception):
    """No group matches the given id, or the id was not a valid group id."""


def resolve_group(session: Session, group_id: str) -> Group:
    """The `Group` row for `group_id`, or `GroupNotFoundError` if it isn't one.

    An `OperationalError` (migration 0005 not applied, so the `groups` table is
    absent) is reported as "not found" too: a caller asking for a group on a
    database that has none is answered 404, never a 500 traceback.
    """
    try:
        numeric_id = int(group_id)
    except (TypeError, ValueError):
        raise GroupNotFoundError(group_id) from None
    try:
        group = session.get(Group, numeric_id)
    except OperationalError as exc:
        raise GroupNotFoundError(group_id) from exc
    if group is None:
        raise GroupNotFoundError(group_id)
    return group


def member_device_ids(session: Session, group_id: int) -> list[str]:
    """Member device_ids in stable (device name) order."""
    stmt = (
        select(DeviceGroup.device_id)
        .join(Device, Device.device_id == DeviceGroup.device_id)
        .where(DeviceGroup.group_id == group_id)
        .order_by(Device.name)
    )
    return [row.device_id for row in session.execute(stmt).all()]


def member_observations(
    session: Session, member_ids: list[str], start_utc: datetime, end_utc: datetime
) -> list[tuple[str, list[LocationObservation]]]:
    """`(device_id, observations)` per member, in member order — never merged."""
    return [(did, fetch_observations(session, did, start_utc, end_utc)) for did in member_ids]


def _labels_for(session: Session, member_ids: list[str]) -> dict[str, str]:
    """device_id -> the user's label, for this group's members only.

    Mirrors `api/_routes_history_export.py::_labels_for`: one query, devices
    without a label are left out so callers fall back to device_id (R-P2-27
    item 1, extended to group exports per the E13 blind-cap S1 finding).
    """
    if not member_ids:
        return {}
    pairs = session.execute(
        select(Device.device_id, Device.label).where(Device.device_id.in_(member_ids))
    ).all()
    return {device_id: label for device_id, label in pairs if label}


def export_group(
    session: Session, group_id: str, fmt: str, start_utc: datetime, end_utc: datetime, zone
) -> tuple[str, str]:
    """Resolve `group_id`, gather every member's history, render `fmt`.

    Returns `(body, filename_stub)`. Raises `GroupNotFoundError` for an
    unknown or non-numeric group_id — callers map that to their own 404.
    """
    group = resolve_group(session, group_id)
    members = member_device_ids(session, group.id)
    blocks = member_observations(session, members, start_utc, end_utc)
    labels = _labels_for(session, members)
    body = render_group(fmt, blocks, zone, group.name, labels)
    return body, group.name.replace(" ", "-")


def render_group(
    fmt: str,
    blocks: list[tuple[str, list[LocationObservation]]],
    zone,
    group_name: str,
    labels: dict[str, str] | None = None,
) -> str:
    """Render `blocks` (one entry per member) in `fmt`. Blocks stay in member order."""
    fmt = fmt.lower()
    renderers = {"csv": _csv, "json": _json, "gpx": _gpx, "kml": _kml}
    if fmt not in renderers:
        raise ValueError(f"Unsupported export format {fmt!r}.")
    if fmt in {"gpx", "kml"}:
        return renderers[fmt](blocks, group_name, labels)
    return renderers[fmt](blocks, zone, labels)


def _csv(blocks, zone, labels: dict[str, str] | None = None) -> str:
    """device_id-first CSV. Reuses `to_csv()` per member; the column it already
    emits for device_id is dropped so the leading one isn't duplicated. The
    per-member `labels` dict is threaded through so the `label` column is
    populated exactly as the single-device CSV export populates it."""
    buf = io.StringIO()
    buf.write(CSV_COMMENT + "\n")
    writer = csv.writer(buf, lineterminator="\n")
    header_written = False
    for device_id, obs in blocks:
        # csv_table() drops to_csv()'s own disclaimer line; this file carries
        # one copy of it, written above, not one per member block.
        reader = csv.reader(io.StringIO(csv_table(to_csv(obs, zone, labels=labels))))
        header = next(reader)
        dup = header.index("device_id")
        if not header_written:
            writer.writerow(["device_id", *[h for i, h in enumerate(header) if i != dup]])
            header_written = True
        for row in reader:
            writer.writerow([device_id, *[v for i, v in enumerate(row) if i != dup]])
    return buf.getvalue()


def _json(blocks, zone, labels: dict[str, str] | None = None) -> str:
    """A flat list (not the single-device metadata wrapper) — device_id is
    already on each observation dict `to_json()` produces. `labels` is passed
    through per member so each observation's `label` field is populated."""
    combined = []
    for _device_id, obs in blocks:
        combined.extend(json.loads(to_json(obs, zone, labels=labels))["observations"])
    return json.dumps(combined, indent=2)


def _zulu(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _gpx(blocks, group_name: str, labels: dict[str, str] | None = None) -> str:
    """One `<trk>` per member inside a single GPX document, never one doc each.

    Track name falls back to device_id without a label, mirroring the
    single-device `to_gpx()` fallback exactly (not device_name)."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="findplus" xmlns="http://www.topografix.com/GPX/1/1">',
        f"  <metadata><name>{escape(group_name)}</name></metadata>",
    ]
    for device_id, obs in blocks:
        name = (labels or {}).get(device_id) or device_id
        lines.append(f"  <trk><name>{escape(name)}</name><trkseg>")
        for o in obs:
            lines.append(f'    <trkpt lat="{o.latitude:.7f}" lon="{o.longitude:.7f}">')
            lines.append(f"      <time>{_zulu(o.observed_at)}</time>")
            lines.append("    </trkpt>")
        lines.append("  </trkseg></trk>")
    lines.append("</gpx>")
    return "\n".join(lines) + "\n"


def _kml(blocks, group_name: str, labels: dict[str, str] | None = None) -> str:
    """One `<Placemark><LineString>` per member inside a single KML document.

    Placemark name falls back to device_id without a label, mirroring the
    single-device `to_kml()` fallback exactly (not device_name)."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
        f"  <name>{escape(group_name)}</name>",
    ]
    for device_id, obs in blocks:
        name = (labels or {}).get(device_id) or device_id
        coords = " ".join(f"{o.longitude:.7f},{o.latitude:.7f},0" for o in obs)
        lines += [
            "  <Placemark>",
            f"    <name>{escape(name)}</name>",
            f"    <LineString><coordinates>{coords}</coordinates></LineString>",
            "  </Placemark>",
        ]
    lines.append("</Document></kml>")
    return "\n".join(lines) + "\n"
