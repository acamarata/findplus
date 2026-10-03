"""Find+ updates: find a newer app, stage it, and hand it to the desktop shell.

Purpose    : Keep the macOS app current with no data lost. The daemon finds and
             verifies the update; the desktop shell installs it with
             packaging/scripts/update-app.sh when the app is not in use.
Modules    : release (the one GitHub request), download (fetch + sha256),
             devsource (developer-only local builds), check (pick and stage),
             status (what the dashboard and shell read), apply (verify again and
             back up before the install), prefs (`updates.auto`), scheduler (the
             background loop).
Constraints: The only network request is a GET to the GitHub releases API for
             acamarata/findplus, plus the download of the release's own files.
             No data about the owner is sent. The history database and the rest
             of the state directory are never moved or changed by an update.
"""
