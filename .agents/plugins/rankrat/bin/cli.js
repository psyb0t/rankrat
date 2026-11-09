#!/usr/bin/env node
// Rankrat MCP bridge: forwards MCP over stdio to a running Rankrat server's
// Streamable HTTP endpoint ($RANKRAT_URL/mcp) through mcp-remote.
//
// stdout is the MCP protocol channel, so diagnostics go to stderr only. The
// bearer header is passed as the literal "${RANKRAT_TOKEN}" placeholder, which
// mcp-remote expands from its own environment, so the token never appears in a
// process argument list.
import { spawnSync } from "node:child_process";
import { realpathSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const MCP_PATH = "/mcp";
const TOKEN_HEADER = "Authorization: Bearer ${RANKRAT_TOKEN}";
const MISSING_URL_MESSAGE = `[rankrat-mcp] Missing RANKRAT_URL.

Point this bridge at your running Rankrat server, e.g.:
  export RANKRAT_URL=http://127.0.0.1:8080
  export RANKRAT_TOKEN="$(<"$HOME/.config/rankrat/secrets/rankrat/http-bearer-token")"

Start the server with: rankrat http -d
Rankrat is self-hosted: see https://github.com/psyb0t/rankrat`;

// proxyArguments returns the mcp-remote argument list, or null when no server
// URL is configured.
export function proxyArguments(environment, extraArguments, proxyEntry) {
  const base = environment.RANKRAT_URL;
  if (!base) {
    return null;
  }
  const url = `${base.replace(/\/+$/u, "")}${MCP_PATH}`;
  const argumentsList = [proxyEntry, url, "--transport", "http-only"];
  if (environment.RANKRAT_TOKEN) {
    argumentsList.push("--header", TOKEN_HEADER);
  }
  argumentsList.push(...extraArguments);
  return argumentsList;
}

export function main(
  environment = process.env,
  extraArguments = process.argv.slice(2),
  spawn = spawnSync,
  resolveProxy = () => createRequire(import.meta.url).resolve("mcp-remote/dist/proxy.js"),
) {
  if (!environment.RANKRAT_URL) {
    console.error(MISSING_URL_MESSAGE);
    return 1;
  }
  const argumentsList = proxyArguments(environment, extraArguments, resolveProxy());
  const result = spawn(process.execPath, argumentsList, { stdio: "inherit", env: environment });
  return result.status ?? 1;
}

function invokedDirectly() {
  if (!process.argv[1]) {
    return false;
  }
  try {
    return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url));
  } catch {
    return false;
  }
}

if (invokedDirectly()) {
  process.exit(main());
}
