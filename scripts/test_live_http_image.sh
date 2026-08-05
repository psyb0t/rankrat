#!/bin/bash
set -euo pipefail

readonly HTTP_PORT=8080
readonly TEST_MEMORY_LIMIT="512m"
readonly TEST_CPU_LIMIT="1"
readonly TEST_PIDS_LIMIT=128
readonly RUNNER_MEMORY_LIMIT="512m"
readonly RUNNER_CPU_LIMIT="1"
readonly RUNNER_PIDS_LIMIT=128
readonly SERVICE_HOSTNAME="rankrat-live-http"
readonly HTTP_BEARER_SECRET_CONTAINER_PATH="/run/secrets/rankrat/http-bearer-token"
readonly RUNNER_SCRIPT="/work/scripts/run_live_http_image.py"
readonly PARENT_BASH_PROCESS_ID="$BASHPID"

log() {
	local level="$1"
	shift
	local timestamp
	timestamp=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
	printf '{"time":"%s","level":"%s","file":"%s","line":%d,"func":"%s","msg":"%s"}\n' \
		"$timestamp" "$level" "${BASH_SOURCE[1]##*/}" "${BASH_LINENO[0]}" \
		"${FUNCNAME[1]:-main}" "$*" >&2
}

usage() {
	printf 'usage: %s <production-image> <development-image> <boundary-file> <secrets-dir> <oauth-dir> <workspace>\n' "${0##*/}" >&2
}

[[ "$#" -eq 6 ]] || {
	usage
	exit 2
}

readonly image_reference="$1"
readonly development_image="$2"
readonly boundary_file="$3"
readonly secret_directory="$4"
readonly oauth_directory="$5"
readonly workspace="$6"
container_uid_gid="$(id -u):$(id -g)"
readonly container_uid_gid

temporary_directory=""
runtime_config_directory=""
container_name=""
container_started=false
service_ip=""

cleanup() {
	if [[ "$BASHPID" != "$PARENT_BASH_PROCESS_ID" ]]; then
		return
	fi
	if [[ "$container_started" == true ]]; then
		# This exact name is generated here and only assigned after docker run succeeds.
		docker rm -f "$container_name" >/dev/null 2>&1 || :
	fi
	if [[ -n "$temporary_directory" ]]; then
		rm -rf -- "$temporary_directory"
	fi
}

log_container_output() {
	if ! docker logs "$container_name" >&2; then
		log WARN "could not retrieve Rankrat container output"
	fi
}

on_error() {
	local exit_status=$?
	log ERROR "production HTTP/MCP live verification failed exit=${exit_status}"
	exit "$exit_status"
}

trap cleanup EXIT
trap on_error ERR

[[ -f "$boundary_file" ]] || {
	log ERROR "boundary file is required"
	exit 1
}
[[ -d "$secret_directory" ]] || {
	log ERROR "secrets directory is required"
	exit 1
}
[[ -d "$oauth_directory" ]] || {
	log ERROR "OAuth directory is required"
	exit 1
}
[[ -d "$workspace" ]] || {
	log ERROR "workspace is required"
	exit 1
}
readonly http_bearer_secret_file="$secret_directory/rankrat/http-bearer-token"
[[ -f "$http_bearer_secret_file" ]] || {
	log ERROR "HTTP bearer secret file is required for production transport verification"
	exit 1
}

temporary_directory=$(mktemp -d "$workspace/.test-live-http.XXXXXX")
runtime_config_directory="$temporary_directory/config"
install -d -m 700 "$runtime_config_directory"
install -m 600 "$boundary_file" "$runtime_config_directory/boundaries.json"
LOG_FILE="${LOG_FILE:-$temporary_directory/live-http-image.log}"
exec > >(tee -a "$LOG_FILE") 2>&1

container_name="rankrat-live-http-$$-${RANDOM}"

readonly -a production_security_args=(
	--init
	--user "$container_uid_gid"
	--read-only
	--cap-drop=ALL
	--security-opt no-new-privileges:true
	--pids-limit "$TEST_PIDS_LIMIT"
	--memory "$TEST_MEMORY_LIMIT"
	--cpus "$TEST_CPU_LIMIT"
	--tmpfs "/tmp:rw,noexec,nosuid,size=32m"
	--mount "type=bind,src=$runtime_config_directory,dst=/run/config,readonly"
	--mount "type=bind,src=$secret_directory,dst=/run/secrets,readonly"
	# Google may rotate a refresh token while satisfying a read request, so this
	# private state path matches the documented production compose contract.
	--mount "type=bind,src=$oauth_directory,dst=/run/oauth"
)

log INFO "starting production Rankrat image on Docker's default egress bridge"
docker run -d --name "$container_name" --network bridge \
	-e RANKRAT_BOUNDARY_FILE=/run/config/boundaries.json \
	-e RANKRAT_SECRET_ROOT=/run/secrets \
	-e RANKRAT_OAUTH_TOKEN_ROOT=/run/oauth \
	-e RANKRAT_HTTP_HOST=0.0.0.0 \
	-e RANKRAT_HTTP_PORT="$HTTP_PORT" \
	-e RANKRAT_HTTP_BEARER_SECRET_FILE="$HTTP_BEARER_SECRET_CONTAINER_PATH" \
	"${production_security_args[@]}" "$image_reference" http >/dev/null
container_started=true
service_ip="$(docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$container_name")"
[[ -n "$service_ip" ]] || {
	log ERROR "could not resolve the production Rankrat bridge address"
	exit 1
}

log INFO "running typed verifier through the production HTTP/MCP transport"
if ! docker run --rm --init --network bridge --add-host "$SERVICE_HOSTNAME:$service_ip" \
	--user "$container_uid_gid" \
	--read-only --cap-drop=ALL --security-opt no-new-privileges:true \
	--pids-limit "$RUNNER_PIDS_LIMIT" --memory "$RUNNER_MEMORY_LIMIT" --cpus "$RUNNER_CPU_LIMIT" \
	--tmpfs /tmp:rw,noexec,nosuid,size=128m \
	-e HOME=/tmp -e XDG_CACHE_HOME=/tmp/cache -e PYTHONDONTWRITEBYTECODE=1 \
	-e PYTHONPATH=/work/src \
	-e RANKRAT_BOUNDARY_FILE=/run/config/boundaries.json \
	-e RANKRAT_SECRET_ROOT=/run/secrets \
	-e RANKRAT_OAUTH_TOKEN_ROOT=/run/oauth \
	--mount "type=bind,src=$workspace,dst=/work,readonly" \
	--mount "type=bind,src=$runtime_config_directory,dst=/run/config,readonly" \
	--mount "type=bind,src=$secret_directory,dst=/run/secrets,readonly" \
	--mount "type=bind,src=$oauth_directory,dst=/run/oauth,readonly" \
	"$development_image" uv run --frozen --no-sync python "$RUNNER_SCRIPT" \
	--base-url "http://${SERVICE_HOSTNAME}:${HTTP_PORT}" \
	--http-bearer-secret-file "$HTTP_BEARER_SECRET_CONTAINER_PATH"; then
	log_container_output
	exit 1
fi

log INFO "production HTTP/MCP live verification passed"
