/*
 * A small, still map for one suggested place.
 *
 * Purpose    : Show where the suggestion is, and how big its circle would be, so
 *              "Name it" is never a leap of faith.
 * Inputs     : A host element, latitude, longitude, radius in metres.
 * Outputs    : { destroy() }. The map cannot be dragged or zoomed.
 * Constraints: Leaflet is the global `L`. Tiles come from the same OpenStreetMap
 *              server the main map uses. Without tiles (offline) the circle still
 *              draws on the plain background.
 */
"use strict";

const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

export function miniMap(host, lat, lon, radius) {
  const map = L.map(host, {
    zoomControl: false, dragging: false, scrollWheelZoom: false, doubleClickZoom: false,
    boxZoom: false, keyboard: false, touchZoom: false, attributionControl: false, zoomSnap: 0,
  });
  L.tileLayer(TILES, { maxZoom: 19 }).addTo(map);
  L.circle([lat, lon], { radius, color: "#3b82f6", fillOpacity: 0.2, interactive: false }).addTo(map);
  // Not circle.getBounds(): that needs the circle to be on a laid-out map already.
  map.fitBounds(L.latLng(lat, lon).toBounds(radius * 3), { padding: [4, 4], animate: false });
  return { destroy: () => map.remove() };
}
