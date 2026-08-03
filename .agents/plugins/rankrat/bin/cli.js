#!/usr/bin/env node
// rankrat MCP bridge. Two transports, selected by RANKRAT_TRANSPORT:
//
//   stdio (default) — runs the published image and lets it speak MCP straight
//     down its own stdio. rankrat's default mode is already stdio, so nothing
//     is proxied here; this only assembles the container invocation.
//   http            — proxies to an already-running server's Streamable HTTP
//     endpoint at $RANKRAT_URL/mcp, with a bearer token when one is configured.
//
// stdout IS the MCP protocol channel in both modes, so diagnostics go to stderr
// only. The sole output is a fatal pre-launch console.error, which is
// user-facing CLI output rather than logging. The bearer token is handed to the
// proxy as an argv header and never printed.
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { resolve } from "node:path";

const require = createRequire(import.meta.url);

const MCP_PATH = "/mcp";
const DEFAULT_IMAGE = "psyb0t/rankrat";
const TRANSPORT_STDIO = "stdio";
const TRANSPORT_HTTP = "http";

// Container-side paths are the server's own defaults, so only the host side is
// configurable. A caller therefore cannot mount a boundary file somewhere the
// server will not read it.
const CONTAINER_CONFIG = "/run/config";
const CONTAINER_SECRETS = "/run/secrets";
const CONTAINER_OAUTH = "/run/oauth";

// Forwarded verbatim so a writable or unbounded session stays an explicit
// choice made by whoever launched the client, never one this bridge makes.
const FORWARDED_SETTINGS = ["RANKRAT_READ_ONLY", "RANKRAT_UNBOUNDED", "RANKRAT_LOG_LEVEL"];

function fail(message) {
  console.error(`[rankrat-mcp] ${message}`);
  process.exit(1);
}

function runHttp() {
  const base = process.env.RANKRAT_URL;
  if (!base) {
    fail(`Missing RANKRAT_URL for RANKRAT_TRANSPORT=http.

Point it at a running rankrat server:
  export RANKRAT_URL=http://127.0.0.1:8080

Or drop RANKRAT_TRANSPORT to use the default stdio transport, which runs the
published image itself.`);
  }

  const url = `${base.replace(/\/+$/, "")}${MCP_PATH}`;
  const token = process.env.RANKRAT_AUTH_TOKEN;
  const args = [require.resolve("mcp-remote/dist/proxy.js"), url, "--transport", "http-only"];

  if (token) {
    args.push("--header", `Authorization: Bearer ${token}`);
  }

  args.push(...process.argv.slice(2));

  return spawnSync(process.execPath, args, { stdio: "inherit" });
}

function runStdio() {
  const configDir = process.env.RANKRAT_CONFIG_DIR;
  if (!configDir) {
    fail(`Missing RANKRAT_CONFIG_DIR for RANKRAT_TRANSPORT=stdio.

rankrat answers only for what its boundary file lists, so it needs that file:
  export RANKRAT_CONFIG_DIR=/path/to/config     # holds boundaries.json
  export RANKRAT_SECRETS_DIR=/path/to/secrets   # provider credentials
  export RANKRAT_OAUTH_DIR=/path/to/oauth       # stored Google OAuth token

See https://github.com/psyb0t/rankrat for how those are created.`);
  }

  const args = [
    "run",
    "--rm",
    "-i",
    "--init",
    "--read-only",
    "--cap-drop=ALL",
    "--security-opt",
    "no-new-privileges:true",
    "--tmpfs",
    "/tmp:rw,noexec,nosuid,size=32m",
    "--mount",
    `type=bind,src=${resolve(configDir)},dst=${CONTAINER_CONFIG},readonly`,
  ];

  // Both are optional: a boundary using only the credential-free tools needs
  // neither, and binding a path that does not exist fails the run outright
  // rather than degrading to a smaller tool surface.
  const secretsDir = process.env.RANKRAT_SECRETS_DIR;
  if (secretsDir) {
    args.push("--mount", `type=bind,src=${resolve(secretsDir)},dst=${CONTAINER_SECRETS},readonly`);
  }

  const oauthDir = process.env.RANKRAT_OAUTH_DIR;
  if (oauthDir) {
    args.push("--mount", `type=bind,src=${resolve(oauthDir)},dst=${CONTAINER_OAUTH},readonly`);
  }

  for (const name of FORWARDED_SETTINGS) {
    if (process.env[name] !== undefined) {
      args.push("-e", `${name}=${process.env[name]}`);
    }
  }

  args.push(process.env.RANKRAT_IMAGE ?? DEFAULT_IMAGE, TRANSPORT_STDIO, ...process.argv.slice(2));

  return spawnSync("docker", args, { stdio: "inherit" });
}

const transport = (process.env.RANKRAT_TRANSPORT ?? TRANSPORT_STDIO).toLowerCase();

if (transport !== TRANSPORT_STDIO && transport !== TRANSPORT_HTTP) {
  fail(`Unknown RANKRAT_TRANSPORT=${transport}. Use "${TRANSPORT_STDIO}" (default) or "${TRANSPORT_HTTP}".`);
}

const result = transport === TRANSPORT_HTTP ? runHttp() : runStdio();

if (result.error) {
  fail(`Could not start the ${transport} transport: ${result.error.message}`);
}

process.exit(result.status ?? 1);
