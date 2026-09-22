/*
 * Badge renderer: the one place a device or group badge is drawn.
 *
 * Purpose    : Turn an icon id, a colour and a name into the coloured disc the
 *              map markers, the timeline track heads, the group legend and the
 *              device and group dialogs all show.
 * Inputs     : { icon, color, label, name, size } — icon in labels.py's
 *              grammar ("lucide:<name>", "letter:<CHAR>", "letter", "none",
 *              "custom:<16-hex-id>"), colour as "#rrggbb", size in px
 *              (default 32).
 * Outputs    : A live SVGElement. The one caller that needs markup instead
 *              (Leaflet's L.divIcon({ html })) reads .outerHTML at its own
 *              call site.
 * Constraints: Pure and import-free, so any module can use it without pulling
 *              in api.js. It never queries the DOM and never loads the sprite:
 *              main.js put the <symbol> elements in the page at boot, and a
 *              pure function has no business owning a network side effect.
 */
"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";

/**
 * The character a badge shows, or null when it draws a glyph or nothing.
 *
 * Mirrors findplus.labels.resolve_icon_letter's branch order: "letter:X"
 * first, then bare "letter", then everything else. One deliberate difference:
 * with no label and no name the Python side returns None and the server-side
 * renderer draws a plain dot, while here the "?" keeps an empty <text> node
 * from being drawn, which would be a silent rendering bug.
 */
export function resolveIconLetter(icon, label, name) {
  if (icon.startsWith("letter:")) return icon.slice(7);
  if (icon === "letter") {
    const text = (label || "").trim() || (name || "").trim();
    return (text[0] || "?").toUpperCase();
  }
  return null;
}

function appendLucideGlyph(svg, icon, size) {
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#lucide-${icon.slice(7)}`);
  use.setAttribute("x", String(size / 4));
  use.setAttribute("y", String(size / 4));
  use.setAttribute("width", String(size / 2));
  use.setAttribute("height", String(size / 2));
  // Lucide strokes with currentColor; setting it on this instance turns the
  // glyph white without touching the shared <symbol>.
  use.style.setProperty("color", "#fff");
  svg.appendChild(use);
}

/**
 * A custom uploaded PNG, clipped to the same disc the colour fill draws, so
 * it fills the badge edge-to-edge while the R-P2-2 ring still shows outside
 * it. One clipPath per call: two badges on screen at once must not share an
 * id, and an SVG id only has to be unique within its own document.
 */
function appendCustomImage(svg, icon, size) {
  const clipId = `fp-badge-clip-${Math.random().toString(36).slice(2)}`;
  const clipPath = document.createElementNS(SVG_NS, "clipPath");
  clipPath.setAttribute("id", clipId);
  const clipCircle = document.createElementNS(SVG_NS, "circle");
  clipCircle.setAttribute("cx", String(size / 2));
  clipCircle.setAttribute("cy", String(size / 2));
  clipCircle.setAttribute("r", String(size / 2 - 1));
  clipPath.appendChild(clipCircle);
  const defs = document.createElementNS(SVG_NS, "defs");
  defs.appendChild(clipPath);
  svg.appendChild(defs);

  const image = document.createElementNS(SVG_NS, "image");
  image.setAttribute("href", `/api/icons/custom/${icon.slice(7)}.png`);
  image.setAttribute("x", "0");
  image.setAttribute("y", "0");
  image.setAttribute("width", String(size));
  image.setAttribute("height", String(size));
  image.setAttribute("preserveAspectRatio", "xMidYMid slice");
  image.setAttribute("clip-path", `url(#${clipId})`);
  svg.appendChild(image);
}

/** A malformed id ("letterX", say) is rejected by labels.validate_icon long
 * before it gets here, but it resolves to null rather than to a character,
 * and a null letter draws the plain disc instead of an empty <text> node. */
function appendLetterText(svg, icon, label, name, size) {
  const letter = resolveIconLetter(icon, label, name);
  if (!letter) return;
  const text = document.createElementNS(SVG_NS, "text");
  text.setAttribute("x", String(size / 2));
  text.setAttribute("y", String(size * 0.65625));
  text.setAttribute("text-anchor", "middle");
  text.setAttribute("font-size", String(size * 0.4375));
  text.setAttribute("font-weight", "700");
  text.setAttribute("fill", "#fff");
  text.textContent = letter;
  svg.appendChild(text);
}

// Every value reaches the DOM through setAttribute or textContent, neither of
// which parses markup, so there is no injection surface and no escaping helper
// is needed here however odd a device name is.
export function renderBadge({ icon, color, label, name, size = 32 }) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));

  const circle = document.createElementNS(SVG_NS, "circle");
  circle.setAttribute("cx", String(size / 2));
  circle.setAttribute("cy", String(size / 2));
  // Inset by half the ring so the whole 2 px stroke stays inside the viewBox;
  // an un-inset radius would clip the ring to a hairline (ruling R-P2-2).
  circle.setAttribute("r", String(size / 2 - 1));
  circle.setAttribute("fill", color);
  circle.setAttribute("stroke", "var(--bg)");
  circle.setAttribute("stroke-width", "2");
  svg.appendChild(circle);

  if (icon.startsWith("lucide:")) {
    appendLucideGlyph(svg, icon, size);
  } else if (icon.startsWith("custom:")) {
    appendCustomImage(svg, icon, size);
  } else if (icon !== "none") {
    appendLetterText(svg, icon, label, name, size);
  }

  return svg;
}
