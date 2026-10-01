/*
 * Timeline rows as one keyboard group.
 *
 * Purpose    : Rows were click-only, so a keyboard user could not pick a point
 *              (UAT #6). The rows are now one roving-tabindex group: exactly one
 *              row is a Tab stop, the arrow keys move between rows (across
 *              tracks), and Enter or Space selects the row, same as a click.
 *              One stop, not one per row, keeps the Tab order short.
 * Inputs     : The #tracks host and a `select(id)` callback.
 * Outputs    : tabindex on every .tl-item; focus moves; select(id) calls.
 * Constraints: Delegated on the host, so a re-render needs only syncRoving().
 */
"use strict";

const rows = (host) => [...host.querySelectorAll(".tl-item")];

/** Make `current` the group's only Tab stop (default: the selected row, else the first). */
export function syncRoving(host, current) {
  const all = rows(host);
  const stop = current || all.find((el) => el.classList.contains("selected")) || all[0];
  all.forEach((el) => { el.tabIndex = el === stop ? 0 : -1; });
}

function move(host, from, key) {
  const all = rows(host);
  const at = all.indexOf(from);
  const next = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: all.length - 1 }[key];
  const target = all[Math.max(0, Math.min(all.length - 1, next))];
  if (target) { syncRoving(host, target); target.focus(); }
}

/** Wire the group once; `select(id)` runs for Enter or Space on a row. */
export function wireTimelineKeys(host, select) {
  host.addEventListener("focusin", (e) => {
    const row = e.target.closest && e.target.closest(".tl-item");
    if (row) syncRoving(host, row);
  });
  host.addEventListener("keydown", (e) => {
    const row = e.target.closest && e.target.closest(".tl-item");
    if (!row || e.target !== row) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      select(Number(row.dataset.id));
    } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
      e.preventDefault();
      move(host, row, e.key);
    }
  });
}
