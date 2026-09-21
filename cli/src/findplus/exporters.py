"""Export observation history to CSV, JSON, GPX and KML.

Purpose : Get history out of the local database in portable formats.
Constraints:
    - GPX track points carry the OBSERVED time (`<time>`), not the retrieval time.
    - Every format carries the "observed locations, not a travelled route"
      disclaimer so an exported file cannot be mistaken for GPS breadcrumbs.
    - Text is XML-escaped; no string concatenation of untrusted values into markup.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from xml.sax.saxutils import escape

from findplus.db.models import LocationObservation
from findplus.geo import haversine_meters

#: Names both networks, never just Google: Find+ exports Apple Find My
#: observations from the same table, and a file that blames one network for
#: rows that came from the other is not honest about where its data came from.
DISCLAIMER = (
    "Observed locations reported via the Find Hub and Find My networks. "
    "Straight lines between points are not the route actually travelled."
)

#: The CSV carries the disclaimer as a leading comment line, so the warning
#: travels with the file the way it already does in JSON, GPX and KML.
#: `csv_table()` strips it back off for any caller that re-parses the output.
CSV_COMMENT = f"# {DISCLAIMER}"


def csv_table(body: str) -> str:
    """`body` without its leading `#` comment lines — header row first."""
    lines = body.split("\n")
    start = 0
    while start < len(lines) and lines[start].startswith("#"):
        start += 1
    return "\n".join(lines[start:])


CSV_COLUMNS = [
    "observation_id",
    "device_id",
    "device_name",
    "label",
    "observed_at_utc",
    "observed_at_local",
    "fetched_at_utc",
    "latitude",
    "longitude",
    "accuracy_meters",
    "altitude_meters",
    "source",
    "is_own_report",
    "battery_level",
    "times_returned",
    # "approx_" is not decoration: PROMPT.md §2 invariant 7 requires the
    # distance to read as approximate everywhere, exports included. It is the
    # straight-line gap between two observed fixes, not distance travelled.
    "approx_meters_from_previous",
]


#: Characters a spreadsheet treats as the start of a formula.
_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: object) -> object:
    """Prefix a formula-leading cell with `'` so Excel/Sheets treat it as text.

    Device names come from the provider and from the user, so a name like
    `=HYPERLINK("http://…")` would otherwise execute the moment someone opened
    the export. The apostrophe is the documented spreadsheet escape and is not
    shown in the cell.
    """
    if isinstance(value, str) and value.startswith(_FORMULA_LEAD):
        return "'" + value
    return value


def _local(ts: datetime, tz) -> str:
    return ts.astimezone(tz).isoformat()


def _zulu(ts: datetime) -> str:
    """UTC instant in the Z-suffixed form GPX and KML require."""
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _with_deltas(
    observations: list[LocationObservation],
) -> list[tuple[LocationObservation, float | None]]:
    out: list[tuple[LocationObservation, float | None]] = []
    prev: LocationObservation | None = None
    for obs in observations:
        meters = (
            None
            if prev is None
            else haversine_meters(prev.latitude, prev.longitude, obs.latitude, obs.longitude)
        )
        out.append((obs, meters))
        prev = obs
    return out


def to_csv(
    observations: list[LocationObservation],
    tz,
    labels: dict[str, str] | None = None,
) -> str:
    buf = io.StringIO()
    buf.write(CSV_COMMENT + "\n")
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for obs, meters in _with_deltas(observations):
        writer.writerow(
            {
                "observation_id": obs.id,
                "device_id": _csv_safe(obs.device_id),
                "device_name": _csv_safe(obs.device_name),
                "label": _csv_safe((labels or {}).get(obs.device_id) or ""),
                "observed_at_utc": obs.observed_at.isoformat(),
                "observed_at_local": _local(obs.observed_at, tz),
                "fetched_at_utc": obs.first_fetched_at.isoformat(),
                "latitude": f"{obs.latitude:.7f}",
                "longitude": f"{obs.longitude:.7f}",
                "accuracy_meters": "" if obs.accuracy_meters is None else obs.accuracy_meters,
                "altitude_meters": "" if obs.altitude_meters is None else obs.altitude_meters,
                "source": _csv_safe(obs.source or ""),
                "is_own_report": "" if obs.is_own_report is None else int(obs.is_own_report),
                "battery_level": "" if obs.battery_level is None else obs.battery_level,
                "times_returned": obs.times_returned,
                "approx_meters_from_previous": "" if meters is None else f"{meters:.1f}",
            }
        )
    return buf.getvalue()


def to_json(
    observations: list[LocationObservation],
    tz,
    labels: dict[str, str] | None = None,
) -> str:
    payload = {
        "disclaimer": DISCLAIMER,
        "exported_at": datetime.now(tz).isoformat(),
        "timezone": str(tz),
        "count": len(observations),
        "observations": [
            {
                "id": obs.id,
                "device_id": obs.device_id,
                "device_name": obs.device_name,
                "label": (labels or {}).get(obs.device_id),
                "observed_at_utc": obs.observed_at.isoformat(),
                "observed_at_local": _local(obs.observed_at, tz),
                "fetched_at_utc": obs.first_fetched_at.isoformat(),
                "latitude": obs.latitude,
                "longitude": obs.longitude,
                "accuracy_meters": obs.accuracy_meters,
                "altitude_meters": obs.altitude_meters,
                "source": obs.source,
                "is_own_report": obs.is_own_report,
                "battery_level": obs.battery_level,
                "times_returned": obs.times_returned,
                "meters_from_previous": meters,
            }
            for obs, meters in _with_deltas(observations)
        ],
    }
    return json.dumps(payload, indent=2)


def to_gpx(
    observations: list[LocationObservation],
    tz,
    track_name: str = "Find+ history",
    labels: dict[str, str] | None = None,
) -> str:
    """GPX 1.1 with a single track segment of timestamped points.

    `labels` provides the `<name>` and `<desc>` for each track point;
    falls back to device_id.
    """
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="findplus" '
        'xmlns="http://www.topografix.com/GPX/1/1" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://www.topografix.com/GPX/1/1 '
        'http://www.topografix.com/GPX/1/1/gpx.xsd">',
        "  <metadata>",
        f"    <name>{escape(track_name)}</name>",
        f"    <desc>{escape(DISCLAIMER)}</desc>",
        f"    <time>{datetime.now(tz).astimezone().isoformat()}</time>",
        "  </metadata>",
        "  <trk>",
        f"    <name>{escape(track_name)}</name>",
        f"    <desc>{escape(DISCLAIMER)}</desc>",
        "    <trkseg>",
    ]
    for obs in observations:
        lines.append(f'      <trkpt lat="{obs.latitude:.7f}" lon="{obs.longitude:.7f}">')
        if obs.altitude_meters is not None:
            lines.append(f"        <ele>{obs.altitude_meters:.1f}</ele>")
        # GPX requires UTC with a trailing Z.
        stamp = _zulu(obs.observed_at)
        lines.append(f"        <time>{stamp}</time>")
        if obs.accuracy_meters is not None:
            lines.append(f"        <hdop>{obs.accuracy_meters:.1f}</hdop>")
        label = (labels or {}).get(obs.device_id) or obs.device_id
        lines.append(f"        <name>{escape(label)}</name>")
        lines.append(f"        <desc>{escape(label)}</desc>")
        if obs.source:
            lines.append(f"        <src>{escape(obs.source)}</src>")
        lines.append("      </trkpt>")
    lines += ["    </trkseg>", "  </trk>", "</gpx>", ""]
    return "\n".join(lines)


def to_kml(
    observations: list[LocationObservation],
    tz,
    doc_name: str = "Find+ history",
    labels: dict[str, str] | None = None,
) -> str:
    """KML with numbered placemarks plus a LineString of the observed path.

    `labels` provides the `<name>` for each placemark; falls back to device_id.
    """
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        "  <Document>",
        f"    <name>{escape(doc_name)}</name>",
        f"    <description>{escape(DISCLAIMER)}</description>",
        '    <Style id="observed-path">',
        "      <LineStyle><color>ff2f6fe6</color><width>3</width></LineStyle>",
        "    </Style>",
    ]
    for index, obs in enumerate(observations, start=1):
        local = _local(obs.observed_at, tz)
        detail = f"Observed {local}"
        if obs.accuracy_meters is not None:
            detail += f" (accuracy ~{obs.accuracy_meters:.0f} m)"
        label = (labels or {}).get(obs.device_id) or obs.device_id
        lines += [
            "    <Placemark>",
            f"      <name>{escape(label)} ({index})</name>",
            f"      <description>{escape(detail)}</description>",
            f"      <TimeStamp><when>{_zulu(obs.observed_at)}</when></TimeStamp>",
            "      <Point><coordinates>"
            f"{obs.longitude:.7f},{obs.latitude:.7f},0"
            "</coordinates></Point>",
            "    </Placemark>",
        ]
    if len(observations) > 1:
        coords = " ".join(f"{o.longitude:.7f},{o.latitude:.7f},0" for o in observations)
        lines += [
            "    <Placemark>",
            "      <name>Observed path</name>",
            f"      <description>{escape(DISCLAIMER)}</description>",
            "      <styleUrl>#observed-path</styleUrl>",
            "      <LineString><tessellate>1</tessellate>"
            f"<coordinates>{coords}</coordinates></LineString>",
            "    </Placemark>",
        ]
    lines += ["  </Document>", "</kml>", ""]
    return "\n".join(lines)


EXPORTERS = {"csv": to_csv, "json": to_json, "gpx": to_gpx, "kml": to_kml}
MEDIA_TYPES = {
    "csv": "text/csv",
    "json": "application/json",
    "gpx": "application/gpx+xml",
    "kml": "application/vnd.google-earth.kml+xml",
}


def export(
    fmt: str,
    observations: list[LocationObservation],
    tz,
    name: str = "Find+ history",
    labels: dict[str, str] | None = None,
) -> str:
    fmt = fmt.lower()
    if fmt not in EXPORTERS:
        raise ValueError(f"Unsupported export format {fmt!r}. Choose one of {sorted(EXPORTERS)}.")
    if fmt in {"gpx", "kml"}:
        return EXPORTERS[fmt](observations, tz, name, labels=labels)  # type: ignore[operator]
    return EXPORTERS[fmt](observations, tz, labels=labels)  # type: ignore[operator]
