#!/bin/bash
# Reference IndexNow key deployment helpers for a static site exporter.
#
# Rankrat never deploys the public key itself: `make init-indexnow` writes the
# private key and `make verify-indexnow-key` checks the deployed copy, but the
# step in between belongs to whatever ships the site. These two functions are
# the reference implementation of that step, so the published contract -- a
# root `<key>.txt` whose only content is `<key>` plus a newline -- is owned and
# tested inside this repository instead of inside somebody's exporter.
#
# This file is sourced, not executed: it defines functions, runs nothing, and
# deliberately does not set shell options, because those belong to the caller.

readonly INDEXNOW_KEY_PATTERN='^[A-Za-z0-9-]{8,128}$'

# An exporter that already has a log() keeps it; the guard only fills the gap
# for a caller that sources this file on its own.
if ! declare -F log >/dev/null 2>&1; then
	log() {
		local level="$1"
		shift
		local message="$*"
		local timestamp
		timestamp=$(date -u '+%Y-%m-%dT%H:%M:%S.%3NZ')
		printf '{"time":"%s","level":"%s","file":"%s","line":%d,"func":"%s","msg":"%s"}\n' \
			"$timestamp" "$level" "${BASH_SOURCE[1]##*/}" "${BASH_LINENO[0]}" \
			"${FUNCNAME[1]:-main}" "$message" >&2
	}
fi

# Copy the local IndexNow key into the static site root and print the key on
# stdout. A missing key file means IndexNow is not configured for this site, so
# there is nothing to publish and nothing to fail. A malformed one is fatal:
# serving the wrong key proves ownership of nothing and the failure would only
# surface later, at submission time.
publish_indexnow_key() {
	local static_dir="$1"
	local key_file="$2"
	local key

	if [[ ! -e "$key_file" ]]; then
		log INFO "IndexNow key absent, skipping publication reason=not_configured"
		return 0
	fi
	if [[ ! -f "$key_file" ]]; then
		log ERROR "IndexNow key path must be a regular file reason=key_not_a_file"
		return 1
	fi
	key=$(<"$key_file")
	if [[ ! "$key" =~ $INDEXNOW_KEY_PATTERN ]]; then
		log ERROR "IndexNow key file is malformed reason=key_malformed"
		return 1
	fi
	printf '%s\n' "$key" >"$static_dir/$key.txt"
	log INFO "IndexNow ownership file written"
	printf '%s' "$key"
}

# Fail the release before upload when the archive about to ship does not carry
# the exact ownership file, because a site answering the key URL with anything
# else fails IndexNow verification after the content is already live.
verify_indexnow_archive() {
	local archive_file="$1"
	local key="$2"
	local verification_status

	if [[ -z "$key" ]]; then
		log INFO "IndexNow archive check skipped reason=not_configured"
		return 0
	fi
	if python3 - "$archive_file" "$key" <<'PY'; then
from pathlib import Path
import sys
from zipfile import BadZipFile, ZipFile

archive_file = Path(sys.argv[1])
key = sys.argv[2]

try:
    with ZipFile(archive_file) as archive:
        contents = archive.read(f"{key}.txt")
except (BadZipFile, KeyError, OSError):
    raise SystemExit(1)

if contents != f"{key}\n".encode():
    raise SystemExit(2)
PY
		log INFO "IndexNow ownership file verified in archive"
		return 0
	else
		verification_status=$?
	fi
	if ((verification_status == 1)); then
		log ERROR "static archive is missing the IndexNow ownership file reason=key_file_missing"
		return 1
	fi
	log ERROR "static archive has an invalid IndexNow ownership file reason=key_file_invalid"
	return 1
}
