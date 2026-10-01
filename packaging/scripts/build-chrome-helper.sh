#!/usr/bin/env bash
# Build the Chrome Web Store zip for the Find+ helper extension.
#
# Produces dist/findplus-chrome-helper-<version>.zip containing ONLY the
# extension's runtime files with a manifest that has NO "key" field (the store
# assigns its own id). Standalone: needs only bash, python3 and zip.
#
# The unpacked extension (browser-helper/) keeps its "key" so its id is stable
# for local Load unpacked; this build strips it for the store.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
src_dir="${repo_root}/browser-helper"
dist_dir="${repo_root}/dist"
work_dir="$(mktemp -d)"
trap 'rm -rf "${work_dir}"' EXIT

# Runtime files that belong in the store package (no README, no *.test.mjs).
files=(
  manifest.json
  background.js
  helper_core.js
  content_begin.js
  content_unlock_main.js
  content_unlock_bridge.js
)

for f in "${files[@]}"; do
  if [ ! -f "${src_dir}/${f}" ]; then
    echo "missing extension file: ${f}" >&2
    exit 1
  fi
done

version="$(python3 - "${src_dir}/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1]))
version = manifest.get("version", "")
assert version, "manifest has no version"
print(version)
PY
)"

pyproject_version="$(sed -n 's/^version = "\(.*\)"/\1/p' "${repo_root}/cli/pyproject.toml" | head -1)"
core_version="$(sed -n 's/^export const HELPER_VERSION = "\(.*\)";/\1/p' "${src_dir}/helper_core.js" | head -1)"
if [ "${version}" != "${pyproject_version}" ] || [ "${version}" != "${core_version}" ]; then
  echo "error: version mismatch, refusing to build a store zip:" >&2
  echo "  browser-helper/manifest.json          ${version}" >&2
  echo "  browser-helper/helper_core.js         ${core_version:-<not found>}" >&2
  echo "  cli/pyproject.toml                    ${pyproject_version:-<not found>}" >&2
  echo "Bump all three together (bump-version.sh moves only pyproject), then build again." >&2
  exit 1
fi

# Copy the runtime files, then rewrite manifest.json without the "key" field.
for f in "${files[@]}"; do
  cp "${src_dir}/${f}" "${work_dir}/${f}"
done
python3 - "${work_dir}/manifest.json" <<'PY'
import json
import sys

path = sys.argv[1]
manifest = json.load(open(path))
manifest.pop("key", None)
json.dump(manifest, open(path, "w"), indent=2)
PY

mkdir -p "${dist_dir}"
zip_path="${dist_dir}/findplus-chrome-helper-${version}.zip"
rm -f "${zip_path}"
( cd "${work_dir}" && zip -q -X "${zip_path}" "${files[@]}" )

# Verify: only the expected files, manifest parses, no "key".
listed="$(unzip -Z1 "${zip_path}" | sort)"
expected="$(printf '%s\n' "${files[@]}" | sort)"
if [ "${listed}" != "${expected}" ]; then
  echo "zip contents differ from the expected extension files:" >&2
  diff <(echo "${expected}") <(echo "${listed}") >&2 || true
  exit 1
fi
python3 - "${work_dir}/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1]))
assert "key" not in manifest, "store manifest must not contain a key"
assert manifest["manifest_version"] == 3, "expected Manifest V3"
PY

echo "built ${zip_path}"
