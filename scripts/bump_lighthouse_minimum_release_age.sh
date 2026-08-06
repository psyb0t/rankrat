#!/bin/bash
set -euo pipefail

LOG_FILE="${LOG_FILE:-/tmp/rankrat-bump-lighthouse-minimum-release-age.log}"
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

readonly CONFIG_FILE="lighthouse-worker/pnpm-workspace.yaml"
readonly MINIMUM_RELEASE_AGE_MINUTES="10080"

[[ -f "$CONFIG_FILE" ]] || {
	log ERROR "Lighthouse pnpm configuration was not found"
	exit 1
}

match_count=$(awk '/^minimumReleaseAge: [0-9]+$/ {count++} END {print count + 0}' "$CONFIG_FILE")
[[ "$match_count" == "1" ]] || {
	log ERROR "expected exactly one minimumReleaseAge setting"
	exit 1
}

sed -i -E \
	"s/^minimumReleaseAge: [0-9]+$/minimumReleaseAge: ${MINIMUM_RELEASE_AGE_MINUTES}/" \
	"$CONFIG_FILE" || {
	log ERROR "failed to update Lighthouse dependency age gate"
	exit 1
}
log INFO "Lighthouse dependency age gate updated"
