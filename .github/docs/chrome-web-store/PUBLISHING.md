# Publishing the Find+ helper to the Chrome Web Store

The extension works today as an unpacked load (see `browser-helper/README.md`).
Publishing to the store gives users a one-click install and a stable id. These
are owner steps; the automation only fills in the id afterward.

Developer account (already registered): publisher ID
`b46ee171-8e7f-4277-a578-b2a229aecdb3`.

## Owner steps (one time, in order)

1. Build the store package:

   ```bash
   bash packaging/scripts/build-chrome-helper.sh
   ```

   This writes `dist/findplus-chrome-helper-<version>.zip` with a manifest that
   has no `key` (the store assigns the id) and only the extension's runtime
   files.

2. Generate the listing images (icon and promo are committed; screenshots are
   captured fresh):

   ```bash
   python packaging/scripts/gen-store-images.py            # icon-128, promo-440x280
   python packaging/scripts/gen-store-images.py --screenshots http://127.0.0.1:8647
   ```

   Icon and promo land in `.github/docs/chrome-web-store/images/`. For the
   screenshots, run Find+ first so a seeded dashboard is available.

3. Open the developer console: https://chrome.google.com/webstore/devconsole
   and pay the one-time developer registration fee if the account is new.

4. Click **New item** and upload the zip from step 1 as a **draft**. The console
   now shows the assigned **item ID**.

5. Fill in the listing from `listing.md`: name, short description, full
   description, category (Productivity), the single-purpose statement, one
   justification per permission, "no remote code", and the data-usage
   disclosures.

6. Upload the images from step 2 (128x128 icon, 440x280 promo, at least one
   1280x800 screenshot).

7. Set the privacy policy URL to
   https://github.com/acamarata/findplus/wiki/Chrome-helper-privacy .

8. Save the draft. Do not submit for review yet.

## Follow-up for the maintainer (after step 4 gives an item ID)

1. Put the assigned item id into
   `cli/src/findplus/providers/google_findhub/helper_state.py`:

   ```python
   CHROME_WEB_STORE_HELPER_ID = "<the item id from the console>"
   ```

   The daemon then trusts helper posts from both the unpacked id and the store
   id. Ship it in a patch release.

2. Release 1.1.5 (owner-gated version bump and tag), then in the console submit
   the draft for review.

## Later versions (optional, once credentials are in the vault)

The Chrome Web Store API can upload and publish new versions without the
console. It needs an OAuth client id, client secret and refresh token in
`~/.claude/vault.env`. When those exist, a future `build-chrome-helper.sh
--upload` step can call the API; until then, uploads are manual through the
console.
