# Packaging and release

How a Find+ release is built and published. Maintainer notes.

## Pieces

| Artefact | Built by | Notes |
|---|---|---|
| Wheel and sdist | `build-python` job | Attached to the GitHub release. Find+ is not on PyPI. |
| macOS dmg (Apple Silicon) | `build-dmg` job, or `packaging/scripts/release-local.sh` | Signed and notarised. The only dmg attached to a release. |
| `install.sh`, `update-app.sh` | copied from the repo | `install.sh` gets the released version baked in. |
| Homebrew formula | `update-tap` job | See below. |

There is no Intel app. The workflow still builds an x86_64 leg for testing; its output is never attached.

## Tag runs

Pushing a `v*` tag runs `.github/workflows/release.yml`.

- The dmg job fails at once if the `APPLE_*` signing secrets are empty. A tag run never produces an
  unsigned app. To release without those secrets, build the dmg locally with `release-local.sh`.
- The release is created as a **draft**. A draft's assets are not public, so nothing downstream runs
  until you publish it.
- A release that is already published is left alone.
- Files whose name contains `UNSIGNED`, and the x86_64 dmg, are never uploaded.
- Workflow permissions default to `contents: read`; only the release job gets `contents: write`.

PyPI publishing is off. Set the repository variable `PUBLISH_PYPI=true` to turn it on.

## The Homebrew tap job

`update-tap` is an outbound write to another repository, so it has three gates:

1. It runs only for a tag, after the release job succeeded.
2. It skips while the release is still a draft. Publish the release, then re-run the job.
3. It skips when the repository secret `TAP_PUSH_TOKEN` is not set.

When all three pass it hashes the sdist attached to the release, writes the formula, pushes a branch
`release-<version>` to `acamarata/homebrew-tap` and opens a pull request. It never merges. Make the
token a fine-grained token limited to that one repository, with contents and pull-request write only.
To turn the job off, leave `TAP_PUSH_TOKEN` unset.

## Licence notices

`python packaging/scripts/third-party-licenses.py` writes
`desktop/src-tauri/notices/THIRD-PARTY-NOTICES.txt` from the runtime dependency closure of
`findplus[bundle,apple]` (no dev tools). Tauri ships that file inside the app. Regenerate it in a
virtualenv with those extras after a dependency change.

## Updating an installed app

`update-app.sh` verifies the dmg against the sha256 on the same release. That detects a corrupted
download only; it does not prove who published the release.
