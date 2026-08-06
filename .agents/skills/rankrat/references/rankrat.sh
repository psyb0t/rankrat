#!/bin/bash
# rankrat.sh -- host wrapper around `docker run` for the published Rankrat image.
#
# The image is the product and `docker run` is the supported contract, documented
# in the README. This script is that contract made executable, so the invocation
# does not have to be retyped -- and drift -- across a Makefile, a README, an
# agent skill and an MCP bridge. Everything it does can be done by hand.
#
# The first argument is the image's own mode -- stdio (default), http, setup,
# auth-google, revoke-google, onboard-site -- and every remaining argument is
# forwarded to it untouched. This script owns only host-side plumbing: what gets
# mounted where, which port is published, and the container hardening flags.
#
# Host-side settings, read here and never forwarded into the container:
#
#   RANKRAT_IMAGE                 image reference          psyb0t/rankrat:latest
#   RANKRAT_BOUNDARIES            boundary file            ./config/boundaries.json
#   RANKRAT_SECRETS               secrets directory        ./secrets
#   RANKRAT_OAUTH                 OAuth state directory    ./oauth
#   RANKRAT_ENV_FILE              env file, setup only     ./.env
#   RANKRAT_HTTP_PORT             published loopback port  8080
#   RANKRAT_OAUTH_CALLBACK_PORT   published OAuth port     49152
#
# Do NOT put those in `.env`. The server parses its own RANKRAT_* namespace with
# extra="forbid", so an unrecognized RANKRAT_* variable is a hard startup error,
# and `.env` goes straight to the container in setup mode.
#
# RANKRAT_READ_ONLY, RANKRAT_UNBOUNDED and RANKRAT_ALLOW_AGENT_ONBOARDING are
# the server's own settings, read here as well because they decide which tools
# are visible and how the boundary file has to be mounted.
#
# Unlike the scripts under scripts/ this one does not tee to a log file. In stdio
# mode the container's stdout is the MCP channel and this process's stdout is
# that pipe; a tee would sit in the middle of the protocol stream. Diagnostics go
# to stderr only.
set -euo pipefail
trap 'log ERROR "command failed exit=$?"' ERR

readonly DEFAULT_IMAGE="psyb0t/rankrat:latest"
readonly DEFAULT_HTTP_PORT=8080
readonly DEFAULT_OAUTH_CALLBACK_PORT=49152
readonly DEFAULT_BOUNDARY_FILE="config/boundaries.json"
readonly DEFAULT_SECRETS_DIRECTORY="secrets"
readonly DEFAULT_OAUTH_DIRECTORY="oauth"
readonly DEFAULT_ENVIRONMENT_FILE=".env"

readonly CONTAINER_CONFIG_DIRECTORY="/run/config"
readonly CONTAINER_OAUTH_TOKEN_ROOT="/run/oauth"
readonly CONTAINER_SECRET_ROOT="/run/secrets"
readonly CONTAINER_HTTP_BEARER_SECRET_FILE="/run/secrets/rankrat/http-bearer-token"
readonly HOST_HTTP_BEARER_SECRET_RELATIVE_PATH="rankrat/http-bearer-token"
readonly CONTAINER_HTTP_PORT=8080
readonly CONTAINER_HTTP_HOST="0.0.0.0"

readonly LOOPBACK_HOST="127.0.0.1"
readonly MEMORY_LIMIT="512m"
readonly CPU_LIMIT="1"
readonly PIDS_LIMIT=128
readonly TMPFS_SIZE="32m"

readonly GROUP_AND_OTHER_WRITE_BITS=022
readonly GROUP_AND_OTHER_ANY_BITS=077

log() {
	local level="$1"
	shift
	local timestamp
	timestamp=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
	printf '{"time":"%s","level":"%s","file":"%s","line":%d,"func":"%s","msg":"%s"}\n' \
		"$timestamp" "$level" "${BASH_SOURCE[1]##*/}" "${BASH_LINENO[0]}" \
		"${FUNCNAME[1]:-main}" "$*" >&2
}

fail() {
	log ERROR "$*"
	exit 1
}

usage() {
	cat <<'EOF' >&2
usage: rankrat.sh [mode] [image arguments...]

modes:
  stdio           MCP over stdio (default)
  http            REST + Streamable HTTP MCP on a loopback port
  setup           read-only check of the configured providers
  auth-google     authorize the Google OAuth scopes
  revoke-google   revoke one Google OAuth account
  onboard-site    create and record resources for one new site

host settings (environment):
  RANKRAT_IMAGE RANKRAT_BOUNDARIES RANKRAT_SECRETS RANKRAT_OAUTH
  RANKRAT_ENV_FILE RANKRAT_HTTP_PORT RANKRAT_OAUTH_CALLBACK_PORT
  RANKRAT_READ_ONLY RANKRAT_UNBOUNDED RANKRAT_ALLOW_AGENT_ONBOARDING

The README documents the equivalent plain `docker run` invocations.
EOF
}

absolute_path() {
	local path="$1"
	# Deliberately not readlink -f: unbounded mode refuses a symlinked boundary
	# file, and resolving the link here would hide the very thing that check
	# looks for. This makes a relative path absolute and nothing else.
	case "$path" in
	/*) printf '%s' "$path" ;;
	*) printf '%s/%s' "$PWD" "$path" ;;
	esac
}

require_boolean() {
	local name="$1" value="$2"
	case "$value" in
	true | false) return 0 ;;
	*) fail "$name must be either true or false, got '$value'" ;;
	esac
}

# The checks the server depends on before it is allowed to write the boundary
# file back. A writable mount anyone else can reach would let a third party widen
# the allow-list between runs.
require_writable_boundary_is_safe() {
	local boundary_file="$1" boundary_directory="$2" host_user_id
	host_user_id="$(id -u)"

	[[ ! -L "$boundary_file" ]] ||
		fail "$boundary_file must not be a symlink when the boundary file is writable"
	[[ "$((0$(stat -c '%a' "$boundary_file") & GROUP_AND_OTHER_WRITE_BITS))" -eq 0 ]] ||
		fail "$boundary_file must not be group- or world-writable"
	[[ "$((0$(stat -c '%a' "$boundary_directory") & GROUP_AND_OTHER_ANY_BITS))" -eq 0 ]] ||
		fail "$boundary_directory must be owner-only; run chmod 700 $boundary_directory"
	[[ "$(stat -c '%u' "$boundary_file")" -eq "$host_user_id" ]] ||
		fail "$boundary_file must be owned by UID $host_user_id"
	[[ "$(stat -c '%u' "$boundary_directory")" -eq "$host_user_id" ]] ||
		fail "$boundary_directory must be owned by UID $host_user_id"
}

mode="stdio"
if [[ "$#" -gt 0 ]]; then
	mode="$1"
	shift
fi

case "$mode" in
-h | --help | help)
	usage
	exit 0
	;;
stdio | http | setup | auth-google | revoke-google | onboard-site) ;;
*)
	usage
	fail "unknown mode '$mode'"
	;;
esac

image="${RANKRAT_IMAGE:-$DEFAULT_IMAGE}"
boundary_file="$(absolute_path "${RANKRAT_BOUNDARIES:-$DEFAULT_BOUNDARY_FILE}")"
secrets_directory="$(absolute_path "${RANKRAT_SECRETS:-$DEFAULT_SECRETS_DIRECTORY}")"
oauth_directory="$(absolute_path "${RANKRAT_OAUTH:-$DEFAULT_OAUTH_DIRECTORY}")"
environment_file="$(absolute_path "${RANKRAT_ENV_FILE:-$DEFAULT_ENVIRONMENT_FILE}")"
http_port="${RANKRAT_HTTP_PORT:-$DEFAULT_HTTP_PORT}"
oauth_callback_port="${RANKRAT_OAUTH_CALLBACK_PORT:-$DEFAULT_OAUTH_CALLBACK_PORT}"
read_only="${RANKRAT_READ_ONLY:-true}"
unbounded="${RANKRAT_UNBOUNDED:-false}"
allow_agent_onboarding="${RANKRAT_ALLOW_AGENT_ONBOARDING:-false}"

require_boolean RANKRAT_READ_ONLY "$read_only"
require_boolean RANKRAT_UNBOUNDED "$unbounded"
require_boolean RANKRAT_ALLOW_AGENT_ONBOARDING "$allow_agent_onboarding"

if [[ "$allow_agent_onboarding" == "true" && "$read_only" == "true" ]]; then
	fail "RANKRAT_ALLOW_AGENT_ONBOARDING=true requires RANKRAT_READ_ONLY=false"
fi

[[ -f "$boundary_file" ]] || fail "$boundary_file is required"
[[ -d "$secrets_directory" ]] || fail "$secrets_directory is required"
[[ -d "$oauth_directory" ]] || fail "$oauth_directory is required"

boundary_directory="$(cd "$(dirname "$boundary_file")" && pwd)"

# The boundary file's DIRECTORY is what gets mounted, never the file on its own.
# The image bakes /run/config as mode 750 owned by its own `rankrat` user, and a
# single-file bind mount leaves that directory in place -- so a container running
# as the host user cannot traverse into it, and one running as `rankrat` cannot
# read an owner-only host file. Mounting the directory replaces both, and it is
# also what unbounded onboarding needs, since it replaces the file by rename.
runtime_boundary_file="$CONTAINER_CONFIG_DIRECTORY/$(basename "$boundary_file")"
readonly_boundary_mount="type=bind,src=$boundary_directory,dst=$CONTAINER_CONFIG_DIRECTORY,readonly"
writable_boundary_mount="type=bind,src=$boundary_directory,dst=$CONTAINER_CONFIG_DIRECTORY"

serve_boundary_mount="$readonly_boundary_mount"
if [[ "$unbounded" == "true" ]]; then
	[[ "$read_only" == "false" ]] ||
		fail "RANKRAT_UNBOUNDED=true requires RANKRAT_READ_ONLY=false"
	require_writable_boundary_is_safe "$boundary_file" "$boundary_directory"
	serve_boundary_mount="$writable_boundary_mount"
fi

common_arguments=(
	--rm
	--init
	--user "$(id -u):$(id -g)"
	--read-only
	--cap-drop=ALL
	--security-opt no-new-privileges:true
	--pids-limit "$PIDS_LIMIT"
	--memory "$MEMORY_LIMIT"
	--cpus "$CPU_LIMIT"
	--tmpfs "/tmp:rw,noexec,nosuid,size=$TMPFS_SIZE"
	--mount "type=bind,src=$secrets_directory,dst=$CONTAINER_SECRET_ROOT,readonly"
	--mount "type=bind,src=$oauth_directory,dst=$CONTAINER_OAUTH_TOKEN_ROOT"
	-e "RANKRAT_OAUTH_TOKEN_ROOT=$CONTAINER_OAUTH_TOKEN_ROOT"
)

mode_arguments=()
case "$mode" in
stdio)
	mode_arguments=(
		-i
		--mount "$serve_boundary_mount"
		-e "RANKRAT_READ_ONLY=$read_only"
		-e "RANKRAT_UNBOUNDED=$unbounded"
		-e "RANKRAT_ALLOW_AGENT_ONBOARDING=$allow_agent_onboarding"
		-e "RANKRAT_BOUNDARY_FILE=$runtime_boundary_file"
	)
	;;
http)
	[[ -f "$secrets_directory/$HOST_HTTP_BEARER_SECRET_RELATIVE_PATH" ]] ||
		fail "$secrets_directory/$HOST_HTTP_BEARER_SECRET_RELATIVE_PATH is required for HTTP"
	mode_arguments=(
		-p "$LOOPBACK_HOST:$http_port:$CONTAINER_HTTP_PORT"
		--mount "$serve_boundary_mount"
		-e "RANKRAT_READ_ONLY=$read_only"
		-e "RANKRAT_UNBOUNDED=$unbounded"
		-e "RANKRAT_ALLOW_AGENT_ONBOARDING=$allow_agent_onboarding"
		-e "RANKRAT_BOUNDARY_FILE=$runtime_boundary_file"
		-e "RANKRAT_HTTP_HOST=$CONTAINER_HTTP_HOST"
		-e "RANKRAT_HTTP_BEARER_SECRET_FILE=$CONTAINER_HTTP_BEARER_SECRET_FILE"
	)
	;;
setup)
	[[ -f "$environment_file" ]] || fail "$environment_file is required for setup"
	# The only mode that reads .env: the live checks it runs are selected there.
	mode_arguments=(
		--network bridge
		--env-file "$environment_file"
		--mount "$readonly_boundary_mount"
		-e "RANKRAT_BOUNDARY_FILE=$runtime_boundary_file"
	)
	;;
auth-google)
	for argument in "$@"; do
		[[ "$argument" != "--callback-port" ]] ||
			fail "set RANKRAT_OAUTH_CALLBACK_PORT rather than --callback-port; the port has to be published too"
	done
	mode_arguments=(
		-i
		-p "$LOOPBACK_HOST:$oauth_callback_port:$oauth_callback_port"
		--mount "$readonly_boundary_mount"
		-e "RANKRAT_BOUNDARY_FILE=$runtime_boundary_file"
		-e "RANKRAT_SECRET_ROOT=$CONTAINER_SECRET_ROOT"
	)
	# Both flags describe the port publishing above, so they belong here
	# rather than at every call site.
	set -- "$@" --callback-port "$oauth_callback_port" --docker-loopback-proxy
	;;
revoke-google)
	mode_arguments=(
		-i
		--mount "$readonly_boundary_mount"
		-e "RANKRAT_BOUNDARY_FILE=$runtime_boundary_file"
		-e "RANKRAT_SECRET_ROOT=$CONTAINER_SECRET_ROOT"
	)
	;;
onboard-site)
	require_writable_boundary_is_safe "$boundary_file" "$boundary_directory"
	mode_arguments=(
		-i
		--mount "$writable_boundary_mount"
		-e "RANKRAT_READ_ONLY=false"
		-e "RANKRAT_BOUNDARY_FILE=$runtime_boundary_file"
		-e "RANKRAT_SECRET_ROOT=$CONTAINER_SECRET_ROOT"
	)
	;;
esac

log INFO "starting rankrat mode=$mode image=$image read_only=$read_only unbounded=$unbounded agent_onboarding=$allow_agent_onboarding"

exec docker run "${common_arguments[@]}" "${mode_arguments[@]}" "$image" "$mode" "$@"
