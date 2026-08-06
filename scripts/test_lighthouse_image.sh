#!/bin/bash
set -euo pipefail

readonly HEALTH_RETRY_COUNT=30
readonly HEALTH_RETRY_DELAY_SECONDS=1
readonly AUDIT_RETRY_COUNT=240
readonly AUDIT_RETRY_DELAY_SECONDS=1
readonly LIVE_AUDIT_TIMEOUT_SECONDS=70
readonly LIVE_AUDIT_RETRY_COUNT=2
readonly WORKER_AUDIT_TIMEOUT_MILLISECONDS=60000
readonly WORKER_MEMORY_LIMIT="2g"
readonly WORKER_CPU_LIMIT="2"
readonly WORKER_PIDS_LIMIT=256
readonly RANKRAT_MEMORY_LIMIT="512m"
readonly RANKRAT_CPU_LIMIT="1"
readonly RANKRAT_PIDS_LIMIT=128
readonly HTTP_PORT=8080
readonly HTTP_CONNECT_TIMEOUT_SECONDS=3
readonly TEST_HTTP_BEARER_SECRET="test-only-not-a-real-secret-value-000000000000"
readonly HTTP_INVALID_REQUEST_BODY='{"account_id":"google","site_url":"https://example.com/","page_url":"https://example.com/","unexpected":true}'
readonly HTTP_METADATA_REQUEST_BODY='{"account_id":"google","site_url":"https://example.com/","page_url":"https://169.254.169.254/latest/meta-data/"}'
readonly MCP_INITIALIZE_REQUEST='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"rankrat-lighthouse-image-smoke","version":"0"}}}'
readonly MCP_INITIALIZED_NOTIFICATION='{"jsonrpc":"2.0","method":"notifications/initialized"}'
readonly -a LIGHTHOUSE_OPERATIONS=(
	"lighthouse_audit"
	"lighthouse_seo_findings"
	"lighthouse_accessibility_findings"
	"lighthouse_performance_findings"
	"lighthouse_best_practices_findings"
)
readonly -a LIGHTHOUSE_REST_ROUTES=(
	"audits"
	"seo-findings"
	"accessibility-findings"
	"performance-findings"
	"best-practices-findings"
)
readonly PARENT_BASH_PROCESS_ID="$BASHPID"
HOST_USER_ID="$(id -u)"
readonly HOST_USER_ID
HOST_GROUP_ID="$(id -g)"
readonly HOST_GROUP_ID
read -r -d '' MCP_RESPONSE_VALIDATOR <<'PYTHON' || true
import json
import sys

responses = []
for line in sys.stdin:
    try:
        responses.append(json.loads(line))
    except json.JSONDecodeError:
        continue
expected_by_id = {
    2: {"performance", "accessibility", "best-practices", "seo"},
    3: {"seo"},
    4: {"accessibility"},
    5: {"performance"},
    6: {"best-practices"},
}
responses_by_id = {item.get("id"): item for item in responses}
for response_id, expected_categories in expected_by_id.items():
    response = responses_by_id.get(response_id)
    if response is None:
        raise SystemExit(
            f"stdio MCP omitted response id={response_id}; "
            f"response_ids={sorted(responses_by_id)}"
        )
    result = response.get("result", {})
    content = result.get("content", [])
    if not content or not isinstance(content[0].get("text"), str):
        raise SystemExit(f"stdio MCP returned no text content for id={response_id}")
    payload = json.loads(content[0]["text"])
    if result.get("isError") is True:
        raise SystemExit(
            f"Lighthouse tool id={response_id} error code={payload.get('code', 'UNKNOWN')}"
        )
    returned_categories = {item["category"] for item in payload.get("categories", [])}
    if returned_categories != expected_categories:
        raise SystemExit(f"Lighthouse categories are wrong for stdio id={response_id}")
    if not isinstance(payload.get("lighthouse_version"), str):
        raise SystemExit(f"Lighthouse report id={response_id} has no version")
PYTHON
readonly MCP_RESPONSE_VALIDATOR
read -r -d '' HTTP_RESPONSE_VALIDATOR <<'PYTHON' || true
import json
import sys

documents = [json.loads(line) for line in sys.stdin if line.strip()]
expected_by_operation = {
    "lighthouse_audit": {"performance", "accessibility", "best-practices", "seo"},
    "lighthouse_seo_findings": {"seo"},
    "lighthouse_accessibility_findings": {"accessibility"},
    "lighthouse_performance_findings": {"performance"},
    "lighthouse_best_practices_findings": {"best-practices"},
}
if len(documents) != 2 * len(expected_by_operation):
    raise SystemExit("all REST and Streamable HTTP MCP responses are required")
seen = set()
for document in documents:
    transport = document["transport"]
    operation = document["operation"]
    payload = document["payload"]
    identity = (transport, operation)
    if identity in seen:
        raise SystemExit(f"duplicate HTTP smoke response: {identity}")
    seen.add(identity)
    if transport == "mcp":
        result = payload.get("result", {})
        content = result.get("content", [])
        if not content or not isinstance(content[0].get("text"), str):
            raise SystemExit(f"Streamable HTTP MCP returned no text for {operation}")
        payload = json.loads(content[0]["text"])
        if result.get("isError") is True:
            raise SystemExit(
                f"Streamable HTTP {operation} error code={payload.get('code', 'UNKNOWN')}"
            )
    returned_categories = {item["category"] for item in payload.get("categories", [])}
    if returned_categories != expected_by_operation[operation]:
        raise SystemExit(f"wrong {transport} categories for {operation}")
    if not isinstance(payload.get("lighthouse_version"), str):
        raise SystemExit(f"{transport} {operation} has no Lighthouse version")
PYTHON
readonly HTTP_RESPONSE_VALIDATOR
read -r -d '' WORKER_BAD_INPUT_VALIDATOR <<'PYTHON' || true
import httpx

transport = httpx.HTTPTransport(uds="/run/lighthouse/lighthouse.sock")
with httpx.Client(transport=transport, base_url="http://lighthouse") as client:
    metadata = client.post(
        "/v1/audits",
        json={"url": "http://169.254.169.254/latest/meta-data/", "categories": ["seo"]},
    )
    oversized = client.post(
        "/v1/audits",
        content=b"x" * 65_537,
        headers={"content-type": "application/json"},
    )
if metadata.status_code != 400:
    raise SystemExit(f"worker accepted metadata URL: {metadata.status_code}")
if oversized.status_code != 400:
    raise SystemExit(f"worker accepted oversized body: {oversized.status_code}")
PYTHON
readonly WORKER_BAD_INPUT_VALIDATOR

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
	printf 'usage: %s <rankrat-image> <lighthouse-image>\n' "${0##*/}" >&2
}

[[ "$#" -eq 2 ]] || {
	usage
	exit 2
}

readonly rankrat_image="$1"
readonly lighthouse_image="$2"
script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly script_directory
project_directory="$(cd -- "$script_directory/.." && pwd)"
readonly project_directory

temporary_directory=""
worker_container_name=""
worker_started=false
rankrat_container_name=""
rankrat_started=false
runtime_volume_name=""
runtime_volume_created=false

cleanup() {
	if [[ "$BASHPID" != "$PARENT_BASH_PROCESS_ID" ]]; then
		return
	fi
	if [[ "$rankrat_started" == true ]]; then
		# This exact name is assigned only after this script starts Rankrat.
		docker rm -f "$rankrat_container_name" >/dev/null 2>&1 || :
	fi
	if [[ "$worker_started" == true ]]; then
		# This exact name is assigned only after this script starts the worker.
		docker rm -f "$worker_container_name" >/dev/null 2>&1 || :
	fi
	if [[ "$runtime_volume_created" == true ]]; then
		# This exact randomized volume is created only by this script.
		docker volume rm "$runtime_volume_name" >/dev/null 2>&1 || :
	fi
	if [[ -n "$temporary_directory" ]]; then
		rm -rf -- "$temporary_directory"
	fi
}

worker_logs() {
	if [[ "$worker_started" == true ]]; then
		docker logs "$worker_container_name" >&2 || :
	fi
}

fail() {
	log ERROR "$*"
	worker_logs
	return 1
}

on_error() {
	local exit_status=$?
	log ERROR "Lighthouse production-image smoke failed exit=${exit_status}"
	worker_logs
	exit "$exit_status"
}

trap cleanup EXIT
trap on_error ERR

temporary_directory=$(
	trap - EXIT ERR
	mktemp -d "$project_directory/.test-lighthouse-image.XXXXXX"
)
readonly config_directory="$temporary_directory/config"
readonly secret_directory="$temporary_directory/secrets"
readonly oauth_directory="$temporary_directory/oauth"
readonly mcp_input_fifo="$temporary_directory/mcp-input"
readonly mcp_output_file="$temporary_directory/mcp-output.jsonl"
readonly mcp_error_file="$temporary_directory/mcp-error.log"
readonly curl_authorization_config="$temporary_directory/curl-authorization.conf"
readonly http_request_body="{\"account_id\":\"google\",\"site_url\":\"https://example.com/\",\"page_url\":\"https://example.com/\",\"timeout_seconds\":${LIVE_AUDIT_TIMEOUT_SECONDS}}"
install -d -m 755 "$config_directory" "$secret_directory" "$oauth_directory"
install -d -m 700 "$secret_directory/rankrat"
install -m 644 "$project_directory/config/boundaries.json.example" \
	"$config_directory/boundaries.json"
printf '%s\n' "$TEST_HTTP_BEARER_SECRET" >"$secret_directory/rankrat/http-bearer-token"
printf 'header = "Authorization: Bearer %s"\n' "$TEST_HTTP_BEARER_SECRET" \
	>"$curl_authorization_config"
chmod 600 "$secret_directory/rankrat/http-bearer-token" "$curl_authorization_config"
mkfifo -m 600 "$mcp_input_fifo"

runtime_volume_name="rankrat-lighthouse-runtime-$$-${RANDOM}"
docker volume create "$runtime_volume_name" >/dev/null
runtime_volume_created=true

log INFO "initializing the arbitrary-UID Lighthouse socket volume"
docker run --rm --network none --user 0:0 --read-only --cap-drop=ALL \
	--cap-add=CHOWN --cap-add=FOWNER \
	--security-opt no-new-privileges:true --pids-limit 16 --memory 64m --cpus 0.25 \
	--mount "type=volume,src=$runtime_volume_name,dst=/run/lighthouse" \
	--entrypoint /bin/sh "$lighthouse_image" \
	-c 'chmod 1777 /run/lighthouse && touch /run/lighthouse/.initialized && chown -R "$1:$2" /run/lighthouse && chmod 0750 /run/lighthouse' \
	_ "$HOST_USER_ID" "$HOST_GROUP_ID"

worker_container_name="rankrat-lighthouse-smoke-$$-${RANDOM}"
log INFO "starting the hardened Lighthouse companion image"
docker run -d --init --name "$worker_container_name" --network bridge \
	--user "$HOST_USER_ID:$HOST_GROUP_ID" \
	--read-only --cap-drop=ALL --security-opt no-new-privileges:true \
	--pids-limit "$WORKER_PIDS_LIMIT" --memory "$WORKER_MEMORY_LIMIT" \
	--cpus "$WORKER_CPU_LIMIT" --shm-size 1g \
	--tmpfs /tmp:rw,noexec,nosuid,size=1g,mode=1777 \
	--mount "type=volume,src=$runtime_volume_name,dst=/run/lighthouse" \
	-e LIGHTHOUSE_RUNNER_TIMEOUT_MS="$WORKER_AUDIT_TIMEOUT_MILLISECONDS" \
	"$lighthouse_image" >/dev/null
worker_started=true

log INFO "waiting for the worker Unix socket health endpoint"
for ((attempt = 1; attempt <= HEALTH_RETRY_COUNT; attempt++)); do
	if docker run --rm --network none --read-only --cap-drop=ALL \
		--user "$HOST_USER_ID:$HOST_GROUP_ID" \
		--security-opt no-new-privileges:true --pids-limit 32 --memory 128m --cpus 0.25 \
		--tmpfs /tmp:rw,noexec,nosuid,size=16m \
		--mount "type=volume,src=$runtime_volume_name,dst=/run/lighthouse,readonly" \
		--entrypoint python "$rankrat_image" -c \
		'import httpx; transport=httpx.HTTPTransport(uds="/run/lighthouse/lighthouse.sock"); response=httpx.Client(transport=transport).get("http://lighthouse/healthz"); response.raise_for_status()' \
		>/dev/null 2>&1; then
		break
	fi
	if [[ "$attempt" -eq "$HEALTH_RETRY_COUNT" ]]; then
		log ERROR "Lighthouse worker did not become healthy"
		exit 1
	fi
	sleep "$HEALTH_RETRY_DELAY_SECONDS"
done

log INFO "rejecting bad input against the running worker image"
docker run --rm --network none --read-only --cap-drop=ALL \
	--user "$HOST_USER_ID:$HOST_GROUP_ID" \
	--security-opt no-new-privileges:true --pids-limit 32 --memory 128m --cpus 0.25 \
	--tmpfs /tmp:rw,noexec,nosuid,size=16m \
	--mount "type=volume,src=$runtime_volume_name,dst=/run/lighthouse,readonly" \
	--entrypoint python "$rankrat_image" -c "$WORKER_BAD_INPUT_VALIDATOR"

log INFO "running a public-page Lighthouse audit through production stdio MCP"
rankrat_container_name="rankrat-lighthouse-client-$$-${RANDOM}"
exec 3<>"$mcp_input_fifo"
docker run --rm -i --name "$rankrat_container_name" --network none \
	--user "$HOST_USER_ID:$HOST_GROUP_ID" \
	--read-only --cap-drop=ALL --security-opt no-new-privileges:true \
	--pids-limit "$RANKRAT_PIDS_LIMIT" --memory "$RANKRAT_MEMORY_LIMIT" \
	--cpus "$RANKRAT_CPU_LIMIT" --tmpfs /tmp:rw,noexec,nosuid,size=32m \
	--mount "type=bind,src=$config_directory,dst=/run/config,readonly" \
	--mount "type=bind,src=$secret_directory,dst=/run/secrets,readonly" \
	--mount "type=bind,src=$oauth_directory,dst=/run/oauth,readonly" \
	--mount "type=volume,src=$runtime_volume_name,dst=/run/lighthouse,readonly" \
	-e RANKRAT_BOUNDARY_FILE=/run/config/boundaries.json \
	-e RANKRAT_SECRET_ROOT=/run/secrets \
	-e RANKRAT_OAUTH_TOKEN_ROOT=/run/oauth \
	-e RANKRAT_LIGHTHOUSE_WORKER_SOCKET=/run/lighthouse/lighthouse.sock \
	"$rankrat_image" stdio <"$mcp_input_fifo" >"$mcp_output_file" 2>"$mcp_error_file" &
rankrat_process_id=$!
rankrat_started=true
printf '%s\n' \
	"$MCP_INITIALIZE_REQUEST" \
	"$MCP_INITIALIZED_NOTIFICATION" >&3
mcp_request_id=2
for operation in "${LIGHTHOUSE_OPERATIONS[@]}"; do
	printf '{"jsonrpc":"2.0","id":%d,"method":"tools/call","params":{"name":"%s","arguments":%s}}\n' \
		"$mcp_request_id" "$operation" "$http_request_body" >&3
	for ((attempt = 1; attempt <= AUDIT_RETRY_COUNT; attempt++)); do
		if grep -Eq "\"id\"[[:space:]]*:[[:space:]]*${mcp_request_id}([,}])" \
			"$mcp_output_file"; then
			break
		fi
		if ! kill -0 "$rankrat_process_id" 2>/dev/null; then
			log ERROR "Rankrat stdio exited before returning ${operation}"
			cat "$mcp_error_file" >&2
			exit 1
		fi
		if [[ "$attempt" -eq "$AUDIT_RETRY_COUNT" ]]; then
			log ERROR "Rankrat stdio timed out waiting for ${operation}"
			cat "$mcp_error_file" >&2
			exit 1
		fi
		sleep "$AUDIT_RETRY_DELAY_SECONDS"
	done
	((mcp_request_id += 1))
done

exec 3>&-

docker run --rm -i --network none \
	--read-only --cap-drop=ALL --security-opt no-new-privileges:true \
	--pids-limit 16 --memory 64m --cpus 0.25 --tmpfs /tmp:rw,noexec,nosuid,size=8m \
	--entrypoint python "$rankrat_image" -c "$MCP_RESPONSE_VALIDATOR" \
	<"$mcp_output_file" ||
	fail "stdio MCP returned an invalid Lighthouse result"

docker rm -f "$rankrat_container_name" >/dev/null
rankrat_started=false

log INFO "running public-page Lighthouse audits through REST and Streamable HTTP MCP"
rankrat_container_name="rankrat-lighthouse-http-$$-${RANDOM}"
docker run -d --name "$rankrat_container_name" --network bridge \
	--user "$HOST_USER_ID:$HOST_GROUP_ID" \
	-p "127.0.0.1::${HTTP_PORT}" \
	--read-only --cap-drop=ALL --security-opt no-new-privileges:true \
	--pids-limit "$RANKRAT_PIDS_LIMIT" --memory "$RANKRAT_MEMORY_LIMIT" \
	--cpus "$RANKRAT_CPU_LIMIT" --tmpfs /tmp:rw,noexec,nosuid,size=32m \
	--mount "type=bind,src=$config_directory,dst=/run/config,readonly" \
	--mount "type=bind,src=$secret_directory,dst=/run/secrets,readonly" \
	--mount "type=bind,src=$oauth_directory,dst=/run/oauth,readonly" \
	--mount "type=volume,src=$runtime_volume_name,dst=/run/lighthouse,readonly" \
	-e RANKRAT_BOUNDARY_FILE=/run/config/boundaries.json \
	-e RANKRAT_SECRET_ROOT=/run/secrets \
	-e RANKRAT_OAUTH_TOKEN_ROOT=/run/oauth \
	-e RANKRAT_LIGHTHOUSE_WORKER_SOCKET=/run/lighthouse/lighthouse.sock \
	-e RANKRAT_HTTP_HOST=0.0.0.0 \
	-e RANKRAT_HTTP_PORT="$HTTP_PORT" \
	-e RANKRAT_HTTP_BEARER_SECRET_FILE=/run/secrets/rankrat/http-bearer-token \
	"$rankrat_image" http >/dev/null
rankrat_started=true

port_mapping=$(docker port "$rankrat_container_name" "${HTTP_PORT}/tcp")
host_port="${port_mapping##*:}"
[[ "$host_port" =~ ^[0-9]+$ ]] || fail "Rankrat HTTP did not publish a loopback port"
readonly health_url="http://127.0.0.1:${host_port}/healthz"
readonly lighthouse_rest_base_url="http://127.0.0.1:${host_port}/v1/lighthouse"
readonly streamable_mcp_url="http://127.0.0.1:${host_port}/mcp/"

for ((attempt = 1; attempt <= HEALTH_RETRY_COUNT; attempt++)); do
	if curl --silent --show-error --fail --noproxy '*' --proto '=http' \
		--max-redirs 0 --connect-timeout "$HTTP_CONNECT_TIMEOUT_SECONDS" \
		--max-time "$HTTP_CONNECT_TIMEOUT_SECONDS" "$health_url" >/dev/null; then
		break
	fi
	if [[ "$attempt" -eq "$HEALTH_RETRY_COUNT" ]]; then
		fail "Rankrat Lighthouse HTTP service did not become healthy"
	fi
	sleep "$HEALTH_RETRY_DELAY_SECONDS"
done

log INFO "rejecting unauthenticated and malformed requests against production HTTP"
unauthenticated_rest_status=$(curl --silent --show-error --output /dev/null \
	--write-out '%{http_code}' --noproxy '*' --proto '=http' --max-redirs 0 \
	--connect-timeout "$HTTP_CONNECT_TIMEOUT_SECONDS" --max-time "$HTTP_CONNECT_TIMEOUT_SECONDS" \
	--request POST --header 'Content-Type: application/json' \
	--data "$http_request_body" "$lighthouse_rest_base_url/seo-findings")
[[ "$unauthenticated_rest_status" == 401 ]] ||
	fail "unauthenticated REST returned $unauthenticated_rest_status instead of 401"

unauthenticated_mcp_status=$(curl --silent --show-error --output /dev/null \
	--write-out '%{http_code}' --noproxy '*' --proto '=http' --max-redirs 0 \
	--connect-timeout "$HTTP_CONNECT_TIMEOUT_SECONDS" --max-time "$HTTP_CONNECT_TIMEOUT_SECONDS" \
	--request POST --header 'Content-Type: application/json' \
	--header 'Accept: application/json, text/event-stream' \
	--data "$MCP_INITIALIZE_REQUEST" "$streamable_mcp_url")
[[ "$unauthenticated_mcp_status" == 401 ]] ||
	fail "unauthenticated Streamable HTTP MCP returned $unauthenticated_mcp_status instead of 401"

invalid_request_status=$(curl --silent --show-error --output /dev/null \
	--write-out '%{http_code}' --config "$curl_authorization_config" \
	--noproxy '*' --proto '=http' --max-redirs 0 \
	--connect-timeout "$HTTP_CONNECT_TIMEOUT_SECONDS" --max-time "$HTTP_CONNECT_TIMEOUT_SECONDS" \
	--request POST --header 'Content-Type: application/json' \
	--data "$HTTP_INVALID_REQUEST_BODY" "$lighthouse_rest_base_url/audits")
[[ "$invalid_request_status" == 422 ]] ||
	fail "over-posted REST request returned $invalid_request_status instead of 422"

metadata_request_status=$(curl --silent --show-error --output /dev/null \
	--write-out '%{http_code}' --config "$curl_authorization_config" \
	--noproxy '*' --proto '=http' --max-redirs 0 \
	--connect-timeout "$HTTP_CONNECT_TIMEOUT_SECONDS" --max-time "$HTTP_CONNECT_TIMEOUT_SECONDS" \
	--request POST --header 'Content-Type: application/json' \
	--data "$HTTP_METADATA_REQUEST_BODY" "$lighthouse_rest_base_url/audits")
[[ "$metadata_request_status" == 400 ]] ||
	fail "metadata-shaped REST request returned $metadata_request_status instead of 400"

curl --silent --show-error --fail --config "$curl_authorization_config" \
	--noproxy '*' --proto '=http' --max-redirs 0 \
	--connect-timeout "$HTTP_CONNECT_TIMEOUT_SECONDS" --max-time "$HTTP_CONNECT_TIMEOUT_SECONDS" \
	--request POST --header 'Content-Type: application/json' \
	--header 'Accept: application/json, text/event-stream' \
	--data "$MCP_INITIALIZE_REQUEST" "$streamable_mcp_url" >/dev/null
curl --silent --show-error --fail --config "$curl_authorization_config" \
	--noproxy '*' --proto '=http' --max-redirs 0 \
	--connect-timeout "$HTTP_CONNECT_TIMEOUT_SECONDS" --max-time "$HTTP_CONNECT_TIMEOUT_SECONDS" \
	--request POST --header 'Content-Type: application/json' \
	--header 'Accept: application/json, text/event-stream' \
	--data "$MCP_INITIALIZED_NOTIFICATION" "$streamable_mcp_url" >/dev/null
readonly http_response_file="$temporary_directory/http-responses.jsonl"
for index in "${!LIGHTHOUSE_OPERATIONS[@]}"; do
	operation="${LIGHTHOUSE_OPERATIONS[$index]}"
	route="${LIGHTHOUSE_REST_ROUTES[$index]}"
	if ! rest_response=$(curl --silent --show-error --fail \
		--retry "$LIVE_AUDIT_RETRY_COUNT" --retry-all-errors \
		--retry-delay "$AUDIT_RETRY_DELAY_SECONDS" \
		--config "$curl_authorization_config" --noproxy '*' --proto '=http' \
		--max-redirs 0 --connect-timeout "$HTTP_CONNECT_TIMEOUT_SECONDS" \
		--max-time "$AUDIT_RETRY_COUNT" --request POST \
		--header 'Content-Type: application/json' --data "$http_request_body" \
		"$lighthouse_rest_base_url/$route"); then
		fail "REST ${operation} failed after bounded retries"
	fi
	printf '{"transport":"rest","operation":"%s","payload":%s}\n' \
		"$operation" "$rest_response" >>"$http_response_file"

	printf -v mcp_request \
		'{"jsonrpc":"2.0","id":%d,"method":"tools/call","params":{"name":"%s","arguments":%s}}' \
		"$((index + 2))" "$operation" "$http_request_body"
	if ! streamable_mcp_response=$(curl --silent --show-error --fail \
		--retry "$LIVE_AUDIT_RETRY_COUNT" --retry-all-errors \
		--retry-delay "$AUDIT_RETRY_DELAY_SECONDS" \
		--config "$curl_authorization_config" --noproxy '*' --proto '=http' \
		--max-redirs 0 --connect-timeout "$HTTP_CONNECT_TIMEOUT_SECONDS" \
		--max-time "$AUDIT_RETRY_COUNT" --request POST \
		--header 'Content-Type: application/json' \
		--header 'Accept: application/json, text/event-stream' \
		--data "$mcp_request" "$streamable_mcp_url"); then
		fail "Streamable HTTP MCP ${operation} failed after bounded retries"
	fi
	printf '{"transport":"mcp","operation":"%s","payload":%s}\n' \
		"$operation" "$streamable_mcp_response" >>"$http_response_file"
done

docker run --rm -i --network none --read-only --cap-drop=ALL \
	--security-opt no-new-privileges:true --pids-limit 16 --memory 64m --cpus 0.25 \
	--tmpfs /tmp:rw,noexec,nosuid,size=8m --entrypoint python \
	"$rankrat_image" -c "$HTTP_RESPONSE_VALIDATOR" <"$http_response_file" ||
	fail "REST or Streamable HTTP MCP returned an invalid Lighthouse result"

log INFO "Lighthouse production-image stdio, REST, and Streamable HTTP smokes passed"
