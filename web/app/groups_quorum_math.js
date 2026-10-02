/*
 * Group quorum arithmetic, the client's copy of groups/quorum.py's quorum_needed().
 *
 * Purpose    : The group dialog shows "Alerts when 2 of 3 members ..." while the
 *              person edits. The number comes from the same rule the engine uses:
 *              any = 1, majority = half the members plus one (rounded down), all =
 *              every member, a number = that many (never more than the members).
 * Inputs     : The quorum value ("any", "majority", "all" or digits) and the number
 *              of members counted.
 * Outputs    : How many members must cross; 0 when there is nobody to count or the
 *              value is not usable yet (an empty custom box).
 * Constraints: Pure. Keep in step with quorum.py by hand, like MIN_PIN_LENGTH.
 */
"use strict";

export function quorumNeeded(quorum, considered) {
  if (!considered) return 0;
  if (quorum === "any") return 1;
  if (quorum === "majority") return Math.floor(considered / 2) + 1;
  if (quorum === "all") return considered;
  if (/^\d+$/.test(String(quorum))) return Math.max(1, Math.min(Number(quorum), considered));
  return 0;
}
