#!/usr/bin/env bash
# Coworld build hook: package the game client as a static replay viewer.
# The viewer is a single self-contained HTML file; the observatory opens it
# as index.html?replay=<replay URL> with no game container running.
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${1:?usage: build_replay_viewer.sh /absolute/output/dir}"
if [[ "${output_dir}" != /* || "${output_dir}" == "/" || "${output_dir}" == "${repo_dir}" ]]; then
  echo "unsafe bundle output: ${output_dir}" >&2
  exit 1
fi

rm -rf "${output_dir}"
mkdir -p "${output_dir}"
cp "${repo_dir}/codrawing/game/client/viewer.html" "${output_dir}/index.html"
