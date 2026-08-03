#!/bin/bash
set -euo pipefail

LOG_FILE="${LOG_FILE:-/tmp/rankrat-bump-exclude-newer.log}"
exec > >(tee -a "$LOG_FILE") 2>&1

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

on_error() {
	local exit_status=$?
	log ERROR "command failed exit=${exit_status}"
	exit "${exit_status}"
}

trap on_error ERR

readonly PROJECT_FILE="pyproject.toml"
[[ -f "$PROJECT_FILE" ]] || {
	log ERROR "pyproject.toml was not found"
	exit 1
}

match_count=$(awk '/^exclude-newer = "/ {count++} END {print count + 0}' "$PROJECT_FILE")
[[ "$match_count" == "1" ]] || {
	log ERROR "expected exactly one exclude-newer setting"
	exit 1
}

cutoff=$(date -u -d '7 days ago' +%Y-%m-%dT00:00:00Z)
sed -i -E "s|^exclude-newer = \".*\"|exclude-newer = \"${cutoff}\"|" "$PROJECT_FILE" || {
	log ERROR "failed to update dependency age gate"
	exit 1
}
log INFO "dependency age gate updated"
