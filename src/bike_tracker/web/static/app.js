/*
 * bike-tracker dashboard.
 *
 * Purpose : Render Find Hub observation history as a map + chronological timeline.
 * Constraints:
 *   - Talks ONLY to this machine's local API. Refreshing this page never causes a
 *     Google query; the server polls Google on its own ~5-minute schedule.
 *   - No analytics, no telemetry, no third-party scripts. Leaflet is served locally.
 *   - Straight lines between observations are drawn as an "observed path" and are
 *     explicitly not a travelled route.
 */
"use strict";

const state = {
  config: null,
  day: null,
  timeline: null,
  selectedId: null,
  movementOnly: false,
  map: null,
  layer: null,
  markers: new Map(),
  refreshTimer: null,
};

const $ = (id) => document.getElementById(id);

/* ----------------------------------------------------------- formatting */

function fmtTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function fmtDateTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} sec`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  if (h < 24) return rem ? `${h} hr ${rem} min` : `${h} hr`;
  const d = Math.floor(h / 24);
  return `${d} day${d === 1 ? "" : "s"} ${h % 24} hr`;
}

function fmtDistance(meters) {
  if (meters === null || meters === undefined) return null;
  const miles = meters / 1609.344;
  if (miles < 0.1) return `${Math.round(meters)} m`;
  return `${miles.toFixed(miles < 10 ? 2 : 1)} mi`;
}

function todayLocal() {
  const d = new Date();
  const off = d.getTimezoneOffset() * 60000;
  return new Date(d - off).toISOString().slice(0, 10);
}

function showAlert(message, kind) {
  const el = $("alert");
  if (!message) { el.classList.add("hidden"); return; }
  el.textContent = message;
  el.className = `alert ${kind === "warn" ? "warn" : ""}`;
}

/* ------------------------------------------------------------- fetching */

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { const body = await res.json(); if (body.detail) detail = body.detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

/* ------------------------------------------------------------------ map */

function initMap() {
  state.map = L.map("map", { zoomControl: true, attributionControl: true })
    .setView([39.5, -98.35], 4);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(state.map);
  state.layer = L.layerGroup().addTo(state.map);
}

function numberedIcon(point, index, total) {
  const classes = ["marker-num"];
  if (!point.is_movement) classes.push("jitter");
  if (index === 0) classes.push("first");
  else if (index === total - 1) classes.push("last");
  return L.divIcon({
    className: "",
    html: `<div class="${classes.join(" ")}">${point.sequence}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}

function popupHtml(point) {
  const rows = [
    `<b>${fmtTime(point.observed_at_local)}</b>`,
    `<div>${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}</div>`,
  ];
  if (point.accuracy_meters !== null && point.accuracy_meters !== undefined) {
    rows.push(`<div>Accuracy ~${Math.round(point.accuracy_meters)} m</div>`);
  }
  if (point.seconds_since_previous !== null) {
    rows.push(`<div>${fmtDuration(point.seconds_since_previous)} since previous observation</div>`);
  }
  const dist = fmtDistance(point.meters_from_previous);
  if (dist) rows.push(`<div>${dist} from previous observation</div>`);
  if (point.source) rows.push(`<div style="opacity:.7">Report: ${point.source}</div>`);
  if (!point.is_movement && point.seconds_since_previous !== null) {
    rows.push(`<div style="opacity:.7">Below movement threshold</div>`);
  }
  rows.push(`<div style="opacity:.6;font-size:11px;margin-top:5px">Retrieved ${fmtDateTime(point.fetched_at)}</div>`);
  return rows.join("");
}

function visiblePoints() {
  if (!state.timeline) return [];
  const pts = state.timeline.points;
  return state.movementOnly ? pts.filter((p) => p.is_movement) : pts;
}

function renderMap() {
  state.layer.clearLayers();
  state.markers.clear();
  const points = visiblePoints();
  if (!points.length) return;

  const latlngs = points.map((p) => [p.latitude, p.longitude]);
  if (latlngs.length > 1) {
    L.polyline(latlngs, { color: "#4f8cf7", weight: 3, opacity: 0.75, dashArray: "6 5" })
      .addTo(state.layer)
      .bindTooltip("Observed path — actual route between detections may differ.");
  }

  points.forEach((point, index) => {
    const marker = L.marker([point.latitude, point.longitude], {
      icon: numberedIcon(point, index, points.length),
      title: fmtTime(point.observed_at_local),
    }).addTo(state.layer);
    marker.bindPopup(popupHtml(point));
    marker.on("click", () => selectPoint(point.id, false));
    state.markers.set(point.id, marker);
  });

  state.map.fitBounds(L.latLngBounds(latlngs), { padding: [42, 42], maxZoom: 17 });
}

/* -------------------------------------------------------------- timeline */

function renderTimeline() {
  const list = $("timeline");
  list.innerHTML = "";
  const points = visiblePoints();

  if (!points.length) {
    list.innerHTML = `<li class="empty">No observations recorded for this day.</li>`;
    return;
  }

  points.forEach((point) => {
    if (point.gap_before && point.seconds_since_previous) {
      const gap = document.createElement("li");
      gap.className = "tl-gap";
      gap.textContent = `NO NEW DETECTIONS FOR ${fmtDuration(point.seconds_since_previous).toUpperCase()}`;
      list.appendChild(gap);
    }

    const li = document.createElement("li");
    li.className = "tl-item" + (point.is_movement ? "" : " jitter");
    li.dataset.id = String(point.id);

    const dist = fmtDistance(point.meters_from_previous);
    const meta = [];
    if (dist) meta.push(`${dist} from previous observation`);
    if (point.accuracy_meters != null) meta.push(`±${Math.round(point.accuracy_meters)} m`);
    if (!point.is_movement && point.seconds_since_previous !== null) meta.push("below movement threshold");

    li.innerHTML =
      `<div><span class="tl-seq">${point.sequence}.</span> <span class="tl-time">${fmtTime(point.observed_at_local)}</span></div>` +
      `<div class="tl-coords">📍 ${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}</div>` +
      (meta.length ? `<div class="tl-meta">${meta.join(" · ")}</div>` : "");

    li.addEventListener("click", () => selectPoint(point.id, true));
    list.appendChild(li);
  });

  highlightSelection();
}

function selectPoint(id, panTo) {
  state.selectedId = id;
  highlightSelection();
  const marker = state.markers.get(id);
  if (marker) {
    if (panTo) state.map.panTo(marker.getLatLng(), { animate: true });
    marker.openPopup();
  }
  const li = document.querySelector(`.tl-item[data-id="${id}"]`);
  if (li) li.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function highlightSelection() {
  document.querySelectorAll(".tl-item").forEach((el) => {
    el.classList.toggle("selected", el.dataset.id === String(state.selectedId));
  });
}

/* ----------------------------------------------------------------- stats */

function renderStats() {
  const box = $("stats");
  const stats = state.timeline && state.timeline.stats;
  if (!stats || !stats.observation_count) { box.innerHTML = ""; return; }

  const cells = [
    ["First observation", fmtTime(stats.first_observed_at_local)],
    ["Last observation", fmtTime(stats.last_observed_at_local)],
    ["Unique observations", String(stats.observation_count)],
    ["Meaningful movements", String(stats.movement_count)],
    ["Approx. distance", `${stats.approximate_distance_miles.toFixed(2)} mi`],
    ["Longest gap", fmtDuration(stats.longest_gap_seconds)],
    ["Time span covered", fmtDuration(stats.time_span_seconds)],
  ];

  box.innerHTML =
    cells.map(([label, value]) => `<div class="stat"><b>${value}</b><span>${label}</span></div>`).join("") +
    `<div class="stat-note">${stats.distance_label} — not the distance actually travelled.</div>`;
}

/* --------------------------------------------------------------- loading */

async function loadStatus() {
  try {
    const s = await api("/api/status");
    $("device-name").textContent = s.device ? s.device.name : "no tracker selected";

    const dot = $("live-dot");
    dot.className = "dot " + (s.poller_running ? "live" : "stale");
    dot.title = s.poller_running
      ? `Polling service active (every ${s.poll_interval_minutes} min)`
      : "No recent poll — the service may be stopped";

    const latest = s.latest_observation;
    if (latest) {
      $("card-observed").textContent = fmtTime(latest.observed_at_local);
      $("card-observed-ago").textContent = `${fmtDuration(latest.age_seconds)} ago`;
      $("card-fetched").textContent = fmtTime(latest.fetched_at_local);
      $("card-lag").textContent = `${fmtDuration(latest.retrieval_lag_seconds)} after it was seen`;
    } else {
      $("card-observed").textContent = "—";
      $("card-observed-ago").textContent = "no observations yet";
      $("card-fetched").textContent = "—";
      $("card-lag").textContent = "—";
    }

    const run = s.last_successful_poll;
    $("card-poll").textContent = run ? fmtTime(run.started_at_local) : "—";
    $("card-poll-status").textContent = s.last_poll
      ? `last attempt: ${s.last_poll.status}`
      : "no polls yet";

    $("card-today").textContent = String(s.observations_today);
    $("card-total").textContent = `${s.observations_total} total on record`;

    if (s.last_poll && !["ok", "no_location"].includes(s.last_poll.status)) {
      showAlert(`Last poll failed (${s.last_poll.status}): ${s.last_poll.error_message || "unknown error"}`, "err");
    } else if (!s.device) {
      showAlert("No tracker selected. Run: bike-tracker devices --select <id>", "warn");
    } else if (!s.poller_running) {
      showAlert("The polling service does not appear to be running. Start it with: bike-tracker start", "warn");
    } else {
      showAlert(null);
    }
  } catch (err) {
    showAlert(`Could not reach the local API: ${err.message}`, "err");
  }
}

async function loadDay(day) {
  state.day = day;
  $("day-picker").value = day;
  try {
    state.timeline = await api(`/api/timeline?day=${encodeURIComponent(day)}`);
    state.selectedId = null;
    if (state.timeline.path_disclaimer) {
      $("path-disclaimer").textContent = state.timeline.path_disclaimer;
    }
    renderMap();
    renderTimeline();
    renderStats();
  } catch (err) {
    showAlert(`Could not load ${day}: ${err.message}`, "err");
  }
}

async function loadConfig() {
  state.config = await api("/api/config");
  $("findhub-notice").textContent = state.config.notice;
  return state.config;
}

function shiftDay(days) {
  const d = new Date(state.day + "T12:00:00");
  d.setDate(d.getDate() + days);
  loadDay(d.toISOString().slice(0, 10));
}

/* ----------------------------------------------------------------- wiring */

function wireControls() {
  $("day-picker").addEventListener("change", (e) => loadDay(e.target.value));
  $("btn-today").addEventListener("click", () => loadDay(todayLocal()));
  $("btn-prev-day").addEventListener("click", () => shiftDay(-1));
  $("btn-next-day").addEventListener("click", () => shiftDay(1));

  $("toggle-movement").addEventListener("change", (e) => {
    state.movementOnly = e.target.checked;
    renderMap();
    renderTimeline();
  });

  $("btn-latest").addEventListener("click", async () => {
    try {
      const latest = await api("/api/latest");
      const day = latest.observed_at_local.slice(0, 10);
      if (day !== state.day) await loadDay(day);
      selectPoint(latest.id, true);
      showAlert(
        `Last observed by Find Hub ${fmtDateTime(latest.observed_at_local)} · ` +
        `retrieved ${fmtDateTime(latest.fetched_at_local)} · ` +
        `age ${fmtDuration(latest.age_seconds)}`,
        "warn"
      );
    } catch (err) {
      showAlert(err.message, "warn");
    }
  });

  $("btn-poll").addEventListener("click", async () => {
    const btn = $("btn-poll");
    btn.disabled = true;
    btn.textContent = "Polling…";
    try {
      const r = await api("/api/poll-now", { method: "POST" });
      showAlert(
        r.status === "ok"
          ? `Poll complete: ${r.observations_new} new observation(s), ${r.duplicates} duplicate(s).`
          : `Poll finished with status "${r.status}"${r.error ? `: ${r.error}` : ""}.`,
        r.status === "ok" ? "warn" : "err"
      );
      await loadStatus();
      await loadDay(state.day);
    } catch (err) {
      showAlert(err.message, "err");
    } finally {
      btn.disabled = false;
      btn.textContent = "Poll Now";
    }
  });

  $("btn-export").addEventListener("click", () => {
    const fmt = $("export-format").value;
    const scope = $("export-scope").value;
    const qs = scope === "day" ? `fmt=${fmt}&day=${state.day}` : `fmt=${fmt}`;
    window.location.href = `/api/export?${qs}`;
  });
}

async function main() {
  initMap();
  wireControls();
  const config = await loadConfig();
  await loadStatus();
  await loadDay(todayLocal());

  // Polls the LOCAL API only. Google is queried server-side on its own interval.
  const seconds = Math.max(30, config.ui_refresh_seconds || 45);
  state.refreshTimer = setInterval(async () => {
    await loadStatus();
    if (state.day === todayLocal()) await loadDay(state.day);
  }, seconds * 1000);
}

main();
