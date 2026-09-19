/*
 * bike-tracker dashboard.
 *
 * Purpose : Render Find Hub observation history for one or many trackers as a
 *           map plus per-device chronological timelines.
 * Constraints:
 *   - Talks ONLY to this machine's local API. Refreshing this page never causes
 *     a Google query; the server polls Google on its own schedule.
 *   - Timelines are NEVER merged across devices. Distance and elapsed time
 *     between consecutive points are only meaningful within one tracker.
 *   - No analytics, telemetry or third-party scripts. Leaflet is served locally.
 *   - Straight lines are an "observed path", not a travelled route.
 */
"use strict";

/** Per-device track colours, chosen to stay distinguishable on OSM tiles. */
const TRACK_COLORS = [
  "#4f8cf7", "#e7663f", "#37c67a", "#c77ae6",
  "#e7b53f", "#3fc9d6", "#e64f7a", "#8fb43f",
];

const state = {
  config: null,
  day: null,
  timeline: null,
  devices: [],
  deviceFilter: localStorage.getItem("bt.deviceFilter") || "",
  colors: new Map(),
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
  return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function colorFor(deviceId) {
  if (!state.colors.has(deviceId)) {
    state.colors.set(deviceId, TRACK_COLORS[state.colors.size % TRACK_COLORS.length]);
  }
  return state.colors.get(deviceId);
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

function postJson(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

/* ------------------------------------------------------------------ map */

function initMap() {
  state.map = L.map("map", { zoomControl: true }).setView([39.5, -98.35], 4);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(state.map);
  state.layer = L.layerGroup().addTo(state.map);
}

function numberedIcon(point, index, total, color) {
  const classes = ["marker-num"];
  if (!point.is_movement) classes.push("jitter");
  const bg = point.is_movement ? color : "#6b7688";
  const ring = index === 0 ? "#37c67a" : index === total - 1 ? "#ef5f5f" : "#fff";
  return L.divIcon({
    className: "",
    html: `<div class="${classes.join(" ")}" style="background:${bg};border-color:${ring}">${point.sequence}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}

function popupHtml(point, deviceName) {
  const rows = [
    `<b>${fmtTime(point.observed_at_local)}</b>`,
    `<div style="opacity:.75">${deviceName}</div>`,
    `<div>${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}</div>`,
  ];
  if (point.accuracy_meters != null) {
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

function visiblePoints(track) {
  return state.movementOnly ? track.points.filter((p) => p.is_movement) : track.points;
}

function renderMap() {
  state.layer.clearLayers();
  state.markers.clear();
  if (!state.timeline) return;

  const allLatLngs = [];

  state.timeline.tracks.forEach((track) => {
    const points = visiblePoints(track);
    if (!points.length) return;
    const color = colorFor(track.device_id);
    const latlngs = points.map((p) => [p.latitude, p.longitude]);
    allLatLngs.push(...latlngs);

    if (latlngs.length > 1) {
      L.polyline(latlngs, { color, weight: 3, opacity: 0.75, dashArray: "6 5" })
        .addTo(state.layer)
        .bindTooltip(`${track.device_name} — observed path; actual route between detections may differ.`);
    }

    points.forEach((point, index) => {
      const marker = L.marker([point.latitude, point.longitude], {
        icon: numberedIcon(point, index, points.length, color),
        title: `${track.device_name} · ${fmtTime(point.observed_at_local)}`,
      }).addTo(state.layer);
      marker.bindPopup(popupHtml(point, track.device_name));
      marker.on("click", () => selectPoint(point.id, false));
      state.markers.set(point.id, marker);
    });
  });

  if (allLatLngs.length) {
    state.map.fitBounds(L.latLngBounds(allLatLngs), { padding: [42, 42], maxZoom: 17 });
  }
}

/* -------------------------------------------------------------- tracks */

function statsHtml(stats) {
  if (!stats || !stats.observation_count) return "";
  const cells = [
    ["First observation", fmtTime(stats.first_observed_at_local)],
    ["Last observation", fmtTime(stats.last_observed_at_local)],
    ["Unique observations", String(stats.observation_count)],
    ["Meaningful movements", String(stats.movement_count)],
    ["Approx. distance", `${stats.approximate_distance_miles.toFixed(2)} mi`],
    ["Longest gap", fmtDuration(stats.longest_gap_seconds)],
    ["Time span covered", fmtDuration(stats.time_span_seconds)],
  ];
  return `<div class="stats">` +
    cells.map(([l, v]) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`).join("") +
    `<div class="stat-note">${stats.distance_label} — not the distance actually travelled.</div>` +
    `</div>`;
}

function timelineHtml(track) {
  const points = visiblePoints(track);
  if (!points.length) {
    return `<div class="empty">No observations recorded for this day.</div>`;
  }
  let html = `<ol class="timeline">`;
  points.forEach((point) => {
    if (point.gap_before && point.seconds_since_previous) {
      html += `<li class="tl-gap">NO NEW DETECTIONS FOR ${fmtDuration(point.seconds_since_previous).toUpperCase()}</li>`;
    }
    const dist = fmtDistance(point.meters_from_previous);
    const meta = [];
    if (dist) meta.push(`${dist} from previous observation`);
    if (point.accuracy_meters != null) meta.push(`±${Math.round(point.accuracy_meters)} m`);
    if (!point.is_movement && point.seconds_since_previous !== null) meta.push("below movement threshold");

    html +=
      `<li class="tl-item${point.is_movement ? "" : " jitter"}" data-id="${point.id}">` +
      `<div><span class="tl-seq">${point.sequence}.</span> <span class="tl-time">${fmtTime(point.observed_at_local)}</span></div>` +
      `<div class="tl-coords">📍 ${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}</div>` +
      (meta.length ? `<div class="tl-meta">${meta.join(" · ")}</div>` : "") +
      `</li>`;
  });
  return html + `</ol>`;
}

function renderTracks() {
  const host = $("tracks");
  host.innerHTML = "";
  if (!state.timeline || !state.timeline.tracks.length) {
    host.innerHTML = `<div class="empty">No observations recorded for this day.</div>`;
    return;
  }

  state.timeline.tracks.forEach((track) => {
    const block = document.createElement("section");
    block.className = "track-block";
    block.innerHTML =
      `<div class="track-head">` +
      `<span class="track-swatch" style="background:${colorFor(track.device_id)}"></span>` +
      `<span class="track-name">${track.device_name || track.device_id}</span>` +
      `<span class="track-count">${track.points.length} observation${track.points.length === 1 ? "" : "s"}</span>` +
      `</div>` +
      statsHtml(track.stats) +
      timelineHtml(track);
    host.appendChild(block);
  });

  host.querySelectorAll(".tl-item").forEach((el) => {
    el.addEventListener("click", () => selectPoint(Number(el.dataset.id), true));
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

/* --------------------------------------------------------------- devices */

function renderDeviceFilter() {
  const select = $("device-filter");
  const current = state.deviceFilter;
  select.innerHTML = `<option value="">All tracked devices</option>`;
  state.devices
    .filter((d) => d.is_tracked || d.observation_count > 0)
    .forEach((d) => {
      const opt = document.createElement("option");
      opt.value = d.device_id;
      opt.textContent = d.name + (d.is_tracked ? "" : " (not polled)");
      select.appendChild(opt);
    });
  select.value = current;
  if (select.value !== current) { state.deviceFilter = ""; select.value = ""; }
}

function renderDeviceModal() {
  const host = $("device-list");
  host.innerHTML = "";
  if (!state.devices.length) {
    host.innerHTML = `<div class="empty">No devices known yet. Use "Refresh from Google".</div>`;
  }
  state.devices.forEach((d) => {
    const row = document.createElement("label");
    row.className = "device-row";
    row.innerHTML =
      `<input type="checkbox" value="${d.device_id}" ${d.is_tracked ? "checked" : ""}>` +
      `<span><span class="d-name">${d.name}</span><br><span class="d-id">${d.device_id}</span></span>` +
      `<span class="d-obs">${d.observation_count} obs</span>`;
    row.querySelector("input").addEventListener("change", updateModalRate);
    host.appendChild(row);
  });
  updateModalRate();
}

function updateModalRate() {
  const checked = document.querySelectorAll("#device-list input:checked").length;
  const interval = (state.config && state.config.poll_interval_minutes) || 5;
  const rate = Math.round((checked * 60) / interval);
  $("device-rate").textContent = checked
    ? `${checked} device(s) tracked → about ${rate} Google requests per hour, polled sequentially every ${interval} min.`
    : "Nothing tracked — the poller will not query Google at all.";
}

async function loadDevices() {
  const body = await api("/api/devices");
  state.devices = body.devices;
  state.devices.forEach((d) => colorFor(d.device_id));
  renderDeviceFilter();
  return body;
}

/* --------------------------------------------------------------- loading */

async function loadStatus() {
  try {
    const s = await api(`/api/status${state.deviceFilter ? `?device_id=${encodeURIComponent(state.deviceFilter)}` : ""}`);

    const tracked = s.devices.filter((d) => d.is_tracked);
    $("device-name").textContent = state.deviceFilter
      ? (s.devices.find((d) => d.device_id === state.deviceFilter) || {}).name || state.deviceFilter
      : tracked.length
        ? `${tracked.length} device${tracked.length === 1 ? "" : "s"} tracked · ~${s.requests_per_hour}/hr`
        : "no devices tracked";

    const dot = $("live-dot");
    dot.className = "dot " + (s.poller_running ? "live" : "stale");
    dot.title = s.poller_running
      ? `Polling service active (every ${s.poll_interval_minutes} min)`
      : "No recent poll — the service may be stopped";

    const latest = s.latest_observation;
    if (latest) {
      $("card-observed").textContent = fmtTime(latest.observed_at_local);
      $("card-observed-ago").textContent = `${fmtDuration(latest.age_seconds)} ago · ${latest.device_name}`;
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
    $("card-poll-status").textContent = s.last_poll ? `last attempt: ${s.last_poll.status}` : "no polls yet";
    $("card-today").textContent = String(s.observations_today);
    $("card-total").textContent = `${s.observations_total} total on record`;

    if (s.last_poll && !["ok", "no_location"].includes(s.last_poll.status)) {
      showAlert(`Last poll failed (${s.last_poll.status}): ${s.last_poll.error_message || "unknown error"}`, "err");
    } else if (!s.tracked_count) {
      showAlert('No devices are being tracked. Click "Devices" to choose which trackers to poll.', "warn");
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
  const params = new URLSearchParams({ day });
  if (state.deviceFilter) params.set("device_id", state.deviceFilter);
  try {
    state.timeline = await api(`/api/timeline?${params}`);
    state.selectedId = null;
    if (state.timeline.path_disclaimer) {
      $("path-disclaimer").textContent = state.timeline.path_disclaimer;
    }
    renderMap();
    renderTracks();
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

async function reload() {
  await loadStatus();
  await loadDay(state.day);
}

/* ----------------------------------------------------------------- wiring */

function wireControls() {
  $("device-filter").addEventListener("change", async (e) => {
    state.deviceFilter = e.target.value;
    localStorage.setItem("bt.deviceFilter", state.deviceFilter);
    await reload();
  });

  $("day-picker").addEventListener("change", (e) => loadDay(e.target.value));
  $("btn-today").addEventListener("click", () => loadDay(todayLocal()));
  $("btn-prev-day").addEventListener("click", () => shiftDay(-1));
  $("btn-next-day").addEventListener("click", () => shiftDay(1));

  $("toggle-movement").addEventListener("change", (e) => {
    state.movementOnly = e.target.checked;
    renderMap();
    renderTracks();
  });

  $("export-scope").addEventListener("change", (e) => {
    $("range-inputs").classList.toggle("hidden", e.target.value !== "range");
    if (e.target.value === "range" && !$("range-start").value) {
      $("range-start").value = state.day;
      $("range-end").value = state.day;
    }
  });

  $("btn-export").addEventListener("click", () => {
    const params = new URLSearchParams({ fmt: $("export-format").value });
    const scope = $("export-scope").value;
    if (scope === "day") params.set("day", state.day);
    if (scope === "range") {
      const start = $("range-start").value;
      const end = $("range-end").value;
      if (!start || !end) { showAlert("Pick both a start and an end date.", "warn"); return; }
      if (start > end) { showAlert("The range start is after its end.", "warn"); return; }
      params.set("start", start);
      params.set("end", end);
    }
    if (state.deviceFilter) params.set("device_id", state.deviceFilter);
    window.location.href = `/api/export?${params}`;
  });

  $("btn-latest").addEventListener("click", async () => {
    try {
      const qs = state.deviceFilter ? `?device_id=${encodeURIComponent(state.deviceFilter)}` : "";
      const latest = await api(`/api/latest${qs}`);
      const day = latest.observed_at_local.slice(0, 10);
      if (day !== state.day) await loadDay(day);
      selectPoint(latest.id, true);
      showAlert(
        `${latest.device_name} — last observed by Find Hub ${fmtDateTime(latest.observed_at_local)} · ` +
        `retrieved ${fmtDateTime(latest.fetched_at_local)} · age ${fmtDuration(latest.age_seconds)}`,
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
      const r = await postJson("/api/poll-now");
      const lines = r.results.map((x) => `${x.device_name}: ${x.status}${x.observations_new ? ` (+${x.observations_new})` : ""}`);
      showAlert(`Polled ${r.devices_polled} device(s) — ${r.observations_new} new. ${lines.join(" · ")}`, "warn");
      await reload();
    } catch (err) {
      showAlert(err.message, "err");
    } finally {
      btn.disabled = false;
      btn.textContent = "Poll Now";
    }
  });

  // --- device manager ---
  $("btn-devices").addEventListener("click", async () => {
    await loadDevices();
    renderDeviceModal();
    $("device-modal").classList.remove("hidden");
  });
  $("btn-close-devices").addEventListener("click", () => $("device-modal").classList.add("hidden"));
  $("device-modal").addEventListener("click", (e) => {
    if (e.target.id === "device-modal") $("device-modal").classList.add("hidden");
  });

  $("btn-track-all").addEventListener("click", () => {
    document.querySelectorAll("#device-list input").forEach((i) => { i.checked = true; });
    updateModalRate();
  });
  $("btn-track-none").addEventListener("click", () => {
    document.querySelectorAll("#device-list input").forEach((i) => { i.checked = false; });
    updateModalRate();
  });

  $("btn-refresh-devices").addEventListener("click", async () => {
    const btn = $("btn-refresh-devices");
    btn.disabled = true;
    btn.textContent = "Asking Google…";
    try {
      const r = await postJson("/api/devices/refresh");
      await loadDevices();
      renderDeviceModal();
      showAlert(`Found ${r.found} device(s) on the account.`, "warn");
    } catch (err) {
      showAlert(`Could not refresh devices: ${err.message}`, "err");
    } finally {
      btn.disabled = false;
      btn.textContent = "Refresh from Google";
    }
  });

  $("btn-save-devices").addEventListener("click", async () => {
    const ids = [...document.querySelectorAll("#device-list input:checked")].map((i) => i.value);
    try {
      const r = await postJson("/api/devices/track", { device_ids: ids });
      $("device-modal").classList.add("hidden");
      await loadDevices();
      showAlert(
        r.tracked_count
          ? `Tracking ${r.tracked_count} device(s) — about ${r.requests_per_hour} Google requests/hour.`
          : "No devices tracked. The poller will not query Google.",
        "warn"
      );
      await reload();
    } catch (err) {
      showAlert(err.message, "err");
    }
  });
}

async function main() {
  initMap();
  wireControls();
  const config = await loadConfig();
  await loadDevices();
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
