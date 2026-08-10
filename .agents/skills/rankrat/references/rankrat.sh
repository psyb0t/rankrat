#!/bin/bash
# rankrat.sh -- host wrapper around the published Rankrat images.
#
# Stdio and operator commands use hardened `docker run` invocations. HTTP uses a
# persistent Docker Compose project rooted in RANKRAT_DATA_DIR so Rankrat and its
# Lighthouse companion share one restart policy and one operator-owned profile.
#
# The first argument is the image's own mode -- stdio (default), http, setup,
# auth-google, revoke-google, onboard-site. Non-HTTP arguments are forwarded to
# the image untouched. This script owns host-side mounts, ports and hardening.
#
# Host-side settings, read here and never forwarded into the container:
#
#   RANKRAT_IMAGE                 image reference          psyb0t/rankrat:latest
#   RANKRAT_LIGHTHOUSE_IMAGE      companion image          psyb0t/rankrat-lighthouse:latest
#   RANKRAT_DATA_DIR              persistent profile       $HOME/.config/rankrat
#   RANKRAT_HTTP_PORT             published loopback port  8080
#   RANKRAT_OAUTH_CALLBACK_PORT   published OAuth port     49152
#
# HTTP Compose reads the profile's `.env`, but explicit host values exported by
# this wrapper take precedence. Setup passes `.env` to the Rankrat container.
#
# RANKRAT_READ_ONLY is the server's own setting, read here as well because it
# decides which tools are visible and how the account file has to be mounted.
#
# Unlike the scripts under scripts/ this one does not tee to a log file. In stdio
# mode the container's stdout is the MCP channel and this process's stdout is
# that pipe; a tee would sit in the middle of the protocol stream. Diagnostics go
# to stderr only.
set -euo pipefail
trap 'log ERROR "command failed exit=$?"' ERR

readonly DEFAULT_IMAGE="psyb0t/rankrat:latest"
readonly DEFAULT_LIGHTHOUSE_IMAGE="psyb0t/rankrat-lighthouse:latest"
readonly DEFAULT_HTTP_PORT=8080
readonly DEFAULT_OAUTH_CALLBACK_PORT=49152
readonly DEFAULT_DATA_DIRECTORY_SUFFIX=".config/rankrat"
readonly BOUNDARY_FILE_RELATIVE_PATH="config/boundaries.json"
readonly SECRETS_DIRECTORY_RELATIVE_PATH="secrets"
readonly OAUTH_DIRECTORY_RELATIVE_PATH="oauth"
readonly STATE_DIRECTORY_RELATIVE_PATH="state"
readonly ENVIRONMENT_FILE_RELATIVE_PATH=".env"
readonly COMPOSE_FILE_RELATIVE_PATH="docker-compose.yml"

readonly CONTAINER_CONFIG_DIRECTORY="/run/config"
readonly CONTAINER_OAUTH_TOKEN_ROOT="/run/oauth"
readonly CONTAINER_STATE_DIRECTORY="/run/state"
readonly CONTAINER_STATE_DATABASE="/run/state/rankrat.sqlite3"
readonly CONTAINER_SECRET_ROOT="/run/secrets"
readonly HOST_HTTP_BEARER_SECRET_RELATIVE_PATH="rankrat/http-bearer-token"
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
usage: rankrat.sh [mode] [arguments...]

modes:
  stdio           MCP over stdio (default)
  http [-d]       REST + Streamable HTTP MCP through Docker Compose
                  -d or --detach runs the restartable stack in the background
  setup           guided credential setup, Google OAuth, and live checks
  auth-google     authorize the Google OAuth scopes
  revoke-google   revoke one Google OAuth account
  onboard-site    create and record resources for one new site

host settings (environment):
  RANKRAT_IMAGE RANKRAT_LIGHTHOUSE_IMAGE RANKRAT_DATA_DIR RANKRAT_HTTP_PORT
  RANKRAT_OAUTH_CALLBACK_PORT RANKRAT_READ_ONLY

The README documents direct stdio Docker and Compose HTTP invocations.
EOF
}

data_directory() {
	local directory="${RANKRAT_DATA_DIR:-}"
	if [[ -z "$directory" ]]; then
		[[ -n "${HOME:-}" ]] || fail "RANKRAT_DATA_DIR is required when HOME is unset"
		directory="$HOME/$DEFAULT_DATA_DIRECTORY_SUFFIX"
	fi

	[[ "$directory" == /* ]] || fail "RANKRAT_DATA_DIR must be an absolute path"
	case "$directory" in
	*','* | *$'\r'* | *$'\n'*)
		fail "RANKRAT_DATA_DIR contains a forbidden mount delimiter or line break"
		;;
	esac

	while [[ "$directory" != "/" && "$directory" == */ ]]; do
		directory="${directory%/}"
	done
	[[ "$directory" != "/" ]] || fail "RANKRAT_DATA_DIR must not be the filesystem root"
	[[ ! -L "$directory" && -d "$directory" ]] ||
		fail "RANKRAT_DATA_DIR must be a real directory"
	[[ "$(realpath -- "$directory")" == "$directory" ]] ||
		fail "RANKRAT_DATA_DIR must be canonical and contain no symbolic links"
	printf '%s' "$directory"
}

require_real_directory() {
	local directory="$1" description="$2"
	[[ ! -L "$directory" && -d "$directory" ]] || fail "$description must be a real directory"
	[[ "$(realpath -- "$directory")" == "$directory" ]] ||
		fail "$description must be canonical and contain no symbolic links"
}

require_real_file() {
	local file="$1" description="$2"
	[[ ! -L "$file" && -f "$file" ]] || fail "$description must be a regular file"
	[[ "$(realpath -- "$file")" == "$file" ]] ||
		fail "$description must be canonical and contain no symbolic links"
}

require_boolean() {
	local name="$1" value="$2"
	case "$value" in
	true | false) return 0 ;;
	*) fail "$name must be either true or false, got '$value'" ;;
	esac
}

# The checks the server depends on before it writes discovered inventory back.
# A writable mount anyone else can reach would let a third party replace the
# configured provider accounts between runs.
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

require_owner_only_directory() {
	local directory="$1" description="$2" host_user_id
	host_user_id="$(id -u)"
	[[ ! -L "$directory" && -d "$directory" ]] || fail "$description must be a real directory"
	[[ "$((0$(stat -c '%a' "$directory") & GROUP_AND_OTHER_ANY_BITS))" -eq 0 ]] ||
		fail "$description must be owner-only; run chmod 700 $directory"
	[[ "$(stat -c '%u' "$directory")" -eq "$host_user_id" ]] ||
		fail "$description must be owned by UID $host_user_id"
	[[ -z "$(find "$directory" -type l -print -quit)" ]] ||
		fail "$description must not contain symbolic links"
}

require_compose_project_directory_is_safe() {
	local directory="$1" host_user_id
	host_user_id="$(id -u)"

	[[ "$((0$(stat -c '%a' "$directory") & GROUP_AND_OTHER_WRITE_BITS))" -eq 0 ]] ||
		fail "$directory must not be group- or world-writable for Docker Compose startup"
	[[ "$(stat -c '%u' "$directory")" -eq "$host_user_id" ]] ||
		fail "$directory must be owned by UID $host_user_id for Docker Compose startup"
}

require_compose_file_is_safe() {
	local file="$1" host_user_id
	host_user_id="$(id -u)"

	[[ "$((0$(stat -c '%a' "$file") & GROUP_AND_OTHER_WRITE_BITS))" -eq 0 ]] ||
		fail "$file must not be group- or world-writable"
	[[ "$(stat -c '%u' "$file")" -eq "$host_user_id" ]] ||
		fail "$file must be owned by UID $host_user_id"
}

write_default_compose() {
	cat <<'COMPOSE'
services:
  lighthouse-volume-init:
    image: ${RANKRAT_LIGHTHOUSE_IMAGE:-psyb0t/rankrat-lighthouse:latest}
    entrypoint: ["/bin/sh", "-c"]
    command: ["chmod 1777 /run/lighthouse && touch /run/lighthouse/.initialized && chown -R ${RANKRAT_UID:-10001}:${RANKRAT_GID:-10001} /run/lighthouse && chmod 0750 /run/lighthouse"]
    volumes:
      - lighthouse_runtime:/run/lighthouse
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - FOWNER
    security_opt:
      - no-new-privileges:true
    read_only: true
    user: "0:0"
    pids_limit: 16
    cpus: 0.25
    mem_limit: 64m
    restart: "no"
    network_mode: none

  rankrat:
    image: ${RANKRAT_IMAGE:-psyb0t/rankrat:latest}
    command: ["http"]
    env_file:
      - path: ${RANKRAT_DATA_DIR:-.}/.env
        required: false
    environment:
      RANKRAT_BOUNDARY_FILE: /run/config/boundaries.json
      RANKRAT_SECRET_ROOT: /run/secrets
      RANKRAT_OAUTH_TOKEN_ROOT: /run/oauth
      RANKRAT_STATE_DATABASE: /run/state/rankrat.sqlite3
      RANKRAT_SCHEDULER_INTERVAL_SECONDS: ${RANKRAT_SCHEDULER_INTERVAL_SECONDS:-60}
      RANKRAT_STATE_RETENTION_DAYS: ${RANKRAT_STATE_RETENTION_DAYS:-180}
      RANKRAT_HTTP_BEARER_SECRET_FILE: /run/secrets/rankrat/http-bearer-token
      RANKRAT_HTTP_HOST: 0.0.0.0
      RANKRAT_HTTP_PORT: "8080"
      RANKRAT_LIGHTHOUSE_WORKER_SOCKET: /run/lighthouse/lighthouse.sock
      RANKRAT_LOG_LEVEL: ${RANKRAT_LOG_LEVEL:-INFO}
      RANKRAT_ENABLE_OPENAPI: ${RANKRAT_ENABLE_OPENAPI:-false}
      RANKRAT_READ_ONLY: ${RANKRAT_READ_ONLY:-false}
    ports:
      - "127.0.0.1:${RANKRAT_HTTP_PORT:-8080}:8080"
    volumes:
      # One profile shared with rankrat.sh and every MCP client. Mount the
      # directory, not only boundaries.json, so writable discovery/onboarding
      # can atomically update inventory without depending on image ownership.
      - type: bind
        source: ${RANKRAT_DATA_DIR:-.}/config
        target: /run/config
        read_only: ${RANKRAT_READ_ONLY:-false}
      - ${RANKRAT_DATA_DIR:-.}/secrets:/run/secrets:ro
      - ${RANKRAT_DATA_DIR:-.}/oauth:/run/oauth:rw
      - ${RANKRAT_DATA_DIR:-.}/state:/run/state:rw
      - lighthouse_runtime:/run/lighthouse:ro
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=32m
    init: true
    user: "${RANKRAT_UID:-10001}:${RANKRAT_GID:-10001}"
    pids_limit: 128
    cpus: 1.0
    mem_limit: 512m
    restart: unless-stopped
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).read()"]
      interval: 10s
      timeout: 3s
      retries: 5
      start_period: 15s
    depends_on:
      lighthouse:
        condition: service_healthy
    # Some Docker hosts block analyticsadmin.googleapis.com from user-defined
    # bridges. The default bridge preserves the same container network namespace
    # and outbound provider access without exposing an additional service port.
    network_mode: bridge

  lighthouse:
    image: ${RANKRAT_LIGHTHOUSE_IMAGE:-psyb0t/rankrat-lighthouse:latest}
    environment:
      LIGHTHOUSE_SOCKET_PATH: /run/lighthouse/lighthouse.sock
      LIGHTHOUSE_RUNNER_TIMEOUT_MS: "120000"
    volumes:
      - lighthouse_runtime:/run/lighthouse
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=1g,mode=1777
    shm_size: 1gb
    init: true
    user: "${RANKRAT_UID:-10001}:${RANKRAT_GID:-10001}"
    pids_limit: 256
    cpus: 2.0
    mem_limit: 2g
    restart: unless-stopped
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
    healthcheck:
      test: ["CMD", "node", "dist/health.js"]
      interval: 10s
      timeout: 3s
      retries: 5
      start_period: 15s
    depends_on:
      lighthouse-volume-init:
        condition: service_completed_successfully
    network_mode: bridge

volumes:
  lighthouse_runtime:
COMPOSE
}

ensure_compose_file() {
	local profile_directory="$1" compose_file="$2" temporary_file

	require_compose_project_directory_is_safe "$profile_directory"
	if [[ -e "$compose_file" || -L "$compose_file" ]]; then
		require_real_file "$compose_file" "Rankrat Docker Compose file"
		require_compose_file_is_safe "$compose_file"
		return
	fi

	umask 077
	temporary_file="$(mktemp -- "$profile_directory/.rankrat-compose.XXXXXX")"
	if ! write_default_compose >"$temporary_file"; then
		rm -f -- "$temporary_file"
		fail "could not write temporary Docker Compose configuration"
	fi
	chmod 600 "$temporary_file"
	if ! ln -- "$temporary_file" "$compose_file"; then
		rm -f -- "$temporary_file"
		fail "$compose_file appeared while Docker Compose configuration was being created"
	fi
	rm -f -- "$temporary_file"
	require_real_file "$compose_file" "Rankrat Docker Compose file"
	require_compose_file_is_safe "$compose_file"
	log INFO "created Docker Compose configuration file=$compose_file"
}

run_http_compose() {
	local profile_directory="$1"
	local compose_file="$2"
	local detached="$3"
	local image="$4"
	local lighthouse_image="$5"
	local http_port="$6"
	local read_only="$7"
	local host_user_id host_group_id
	local -a compose_arguments

	ensure_compose_file "$profile_directory" "$compose_file"
	host_user_id="$(id -u)"
	host_group_id="$(id -g)"
	export RANKRAT_DATA_DIR="$profile_directory"
	export RANKRAT_IMAGE="$image"
	export RANKRAT_LIGHTHOUSE_IMAGE="$lighthouse_image"
	export RANKRAT_HTTP_PORT="$http_port"
	export RANKRAT_READ_ONLY="$read_only"
	export RANKRAT_UID="$host_user_id"
	export RANKRAT_GID="$host_group_id"

	compose_arguments=(
		compose
		--project-directory "$profile_directory"
		--file "$compose_file"
		up
	)
	if [[ "$detached" == "true" ]]; then
		compose_arguments+=(--detach)
	fi
	compose_arguments+=(--remove-orphans)

	log INFO "starting Rankrat HTTP Compose project directory=$profile_directory detached=$detached"
	exec docker "${compose_arguments[@]}"
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

http_detached="false"
if [[ "$mode" == "http" ]]; then
	case "$#" in
	0) ;;
	1)
		case "$1" in
		-d | --detach) http_detached="true" ;;
		*) fail "http accepts only -d or --detach" ;;
		esac
		shift
		;;
	*) fail "http accepts only -d or --detach" ;;
	esac
fi

image="${RANKRAT_IMAGE:-$DEFAULT_IMAGE}"
lighthouse_image="${RANKRAT_LIGHTHOUSE_IMAGE:-$DEFAULT_LIGHTHOUSE_IMAGE}"
profile_directory="$(data_directory)"
boundary_file="$profile_directory/$BOUNDARY_FILE_RELATIVE_PATH"
secrets_directory="$profile_directory/$SECRETS_DIRECTORY_RELATIVE_PATH"
oauth_directory="$profile_directory/$OAUTH_DIRECTORY_RELATIVE_PATH"
state_directory="$profile_directory/$STATE_DIRECTORY_RELATIVE_PATH"
environment_file="$profile_directory/$ENVIRONMENT_FILE_RELATIVE_PATH"
compose_file="$profile_directory/$COMPOSE_FILE_RELATIVE_PATH"
http_port="${RANKRAT_HTTP_PORT:-$DEFAULT_HTTP_PORT}"
oauth_callback_port="${RANKRAT_OAUTH_CALLBACK_PORT:-$DEFAULT_OAUTH_CALLBACK_PORT}"
read_only="${RANKRAT_READ_ONLY:-false}"

require_boolean RANKRAT_READ_ONLY "$read_only"

require_real_directory "$profile_directory/config" "Rankrat config directory"
require_real_directory "$secrets_directory" "Rankrat secrets directory"
require_real_directory "$oauth_directory" "Rankrat OAuth directory"
require_real_directory "$state_directory" "Rankrat state directory"
require_real_file "$boundary_file" "Rankrat boundary file"

boundary_directory="$(cd "$(dirname "$boundary_file")" && pwd)"
secret_mount="type=bind,src=$secrets_directory,dst=$CONTAINER_SECRET_ROOT,readonly"
if [[ "$mode" == "setup" ]]; then
	require_writable_boundary_is_safe "$boundary_file" "$boundary_directory"
	require_owner_only_directory "$secrets_directory" "Rankrat secrets directory"
	secret_mount="type=bind,src=$secrets_directory,dst=$CONTAINER_SECRET_ROOT"
fi

# The boundary file's DIRECTORY is what gets mounted, never the file on its own.
# The image bakes /run/config as mode 750 owned by its own `rankrat` user, and a
# single-file bind mount leaves that directory in place -- so a container running
# as the host user cannot traverse into it, and one running as `rankrat` cannot
# read an owner-only host file. Mounting the directory replaces both, and it is
# also what writable onboarding needs, since onboarding replaces the file by
# rename after creating provider resources.
runtime_boundary_file="$CONTAINER_CONFIG_DIRECTORY/$(basename "$boundary_file")"
readonly_boundary_mount="type=bind,src=$boundary_directory,dst=$CONTAINER_CONFIG_DIRECTORY,readonly"
writable_boundary_mount="type=bind,src=$boundary_directory,dst=$CONTAINER_CONFIG_DIRECTORY"

serve_boundary_mount="$readonly_boundary_mount"
if [[ "$read_only" == "false" ]]; then
	require_writable_boundary_is_safe "$boundary_file" "$boundary_directory"
	serve_boundary_mount="$writable_boundary_mount"
fi

if [[ "$mode" == "http" ]]; then
	require_real_file \
		"$secrets_directory/$HOST_HTTP_BEARER_SECRET_RELATIVE_PATH" \
		"Rankrat HTTP bearer secret"
	run_http_compose \
		"$profile_directory" \
		"$compose_file" \
		"$http_detached" \
		"$image" \
		"$lighthouse_image" \
		"$http_port" \
		"$read_only"
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
	--mount "$secret_mount"
	--mount "type=bind,src=$oauth_directory,dst=$CONTAINER_OAUTH_TOKEN_ROOT"
	--mount "type=bind,src=$state_directory,dst=$CONTAINER_STATE_DIRECTORY"
	-e "RANKRAT_OAUTH_TOKEN_ROOT=$CONTAINER_OAUTH_TOKEN_ROOT"
	-e "RANKRAT_STATE_DATABASE=$CONTAINER_STATE_DATABASE"
)

mode_arguments=()
case "$mode" in
stdio)
	mode_arguments=(
		-i
		--mount "$serve_boundary_mount"
		-e "RANKRAT_READ_ONLY=$read_only"
		-e "RANKRAT_BOUNDARY_FILE=$runtime_boundary_file"
	)
	;;
setup)
	require_real_file "$environment_file" "Rankrat setup environment file"
	mode_arguments=(
		-i
		--network bridge
		-p "$LOOPBACK_HOST:$oauth_callback_port:$oauth_callback_port"
		--env-file "$environment_file"
		--mount "$writable_boundary_mount"
		-e "RANKRAT_BOUNDARY_FILE=$runtime_boundary_file"
		-e "RANKRAT_SECRET_ROOT=$CONTAINER_SECRET_ROOT"
	)
	set -- "$@" --interactive-setup --callback-port "$oauth_callback_port" \
		--docker-loopback-proxy --print-authorization-url
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

log INFO "starting rankrat mode=$mode image=$image read_only=$read_only"

exec docker run "${common_arguments[@]}" "${mode_arguments[@]}" "$image" "$mode" "$@"
