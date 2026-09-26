/*
 * Shared dialog-error helpers: turning a raw server error into a sentence.
 *
 * Purpose    : N48: the place and group dialogs showed the server's raw
 *              detail text on a duplicate name ("place name 'Grandma'
 *              already exists"), the field name and Python repr quoting
 *              leaking straight onto the screen. N16 (places part): the same
 *              was true of every other places/repo.py validation message
 *              ("radius_meters must be 20-5000"). One place for each shape.
 * Inputs     : The thrown api()/postJson() error (err.status, err.message)
 *              and, for duplicateNameMessage(), the catalog key to render
 *              the replacement with.
 * Outputs    : A catalog sentence, or null when the error does not match --
 *              the caller falls back to err.message unchanged in that case.
 * Constraints: duplicateNameMessage() only matches status 409 whose detail
 *              is the `'<name>' already exists` shape routes_places.py/
 *              routes_groups.py raise (Python `!r` repr, single quotes). Any
 *              other 409 (or a repr containing an apostrophe) falls through
 *              to the raw message rather than showing a blank or wrong name.
 *              placeValidationMessage() only matches status 422 and the
 *              exact substrings places/repo.py's own ValueErrors raise
 *              (cli/src/findplus/places/repo.py); a message it does not
 *              recognise (a future validation rule) falls through the same
 *              way rather than showing nothing.
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

const PLACE_VALUE_ERRORS = {
  "name must be 1-64 characters": "places.error.nameLength",
  "radius_meters must be 20-5000": "places.error.radiusRange",
  "latitude_e7 out of range": "places.error.locationInvalid",
  "longitude_e7 out of range": "places.error.locationInvalid",
  "enter_confirmations must be 1-5": "places.error.enterRange",
  "exit_confirmations must be 1-5": "places.error.exitRange",
};

/** N16: places_dialog.js's onSave() used to show the server's raw
 * ValueError text straight in the dialog for anything the browser's own
 * `reportValidity()` could not catch first (radius and the lat/lon range,
 * which have no native input constraint here). Matched by exact substring
 * so a message this does not recognise still falls through to the caller's
 * own err.message rather than showing nothing at all. */
export function placeValidationMessage(err) {
  if (err.status !== 422) return null;
  const text = err.message || "";
  for (const [needle, key] of Object.entries(PLACE_VALUE_ERRORS)) {
    if (text.includes(needle)) return t(key);
  }
  return null;
}
