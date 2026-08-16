#!/bin/bash
# Source this file to export and validate a static IndexNow key.

readonly INDEXNOW_KEY_PATTERN='^[A-Za-z0-9-]{8,128}$'

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

# Export a configured key; reject malformed values.
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

# Validate the ownership file before upload.
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
