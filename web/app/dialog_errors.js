/*
 * Shared dialog-error helper: a 409 duplicate-name sentence.
 *
 * Purpose    : N48: the place and group dialogs showed the server's raw
 *              detail text on a duplicate name ("place name 'Grandma'
 *              already exists"), the field name and Python repr quoting
 *              leaking straight onto the screen. One place to turn that into
 *              a catalog sentence, used by both dialogs' save paths.
 * Inputs     : The thrown api()/postJson() error (err.status, err.message)
 *              and the catalog key to render the replacement with.
 * Outputs    : The catalog sentence with {name} filled in, or null when the
 *              error is not a duplicate-name 409 -- the caller falls back to
 *              err.message unchanged for every other error.
 * Constraints: Only reached for status 409 whose detail matches the
 *              `'<name>' already exists` shape routes_places.py/
 *              routes_groups.py raise (Python `!r` repr, single quotes). Any
 *              other 409 (or a repr containing an apostrophe) falls through
 *              to the raw message rather than showing a blank or wrong name.
 */
"use strict";

import { t } from "./i18n.js";

const QUOTED_NAME = /'([^']*)'/;

/** `catalogKey` gets `{name}` substituted; e.g. "groups.error.duplicate_name". */
export function duplicateNameMessage(err, catalogKey) {
  if (err.status !== 409) return null;
  const match = QUOTED_NAME.exec(err.message || "");
  if (!match) return null;
  return t(catalogKey, { name: match[1] });
}
