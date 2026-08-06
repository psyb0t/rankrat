#!/usr/bin/env node
// This is an MCP stdio launcher, not an OpenClaw extension. Its stdout belongs
// exclusively to the Rankrat container's MCP protocol; launcher failures use
// stderr so they cannot corrupt the protocol stream.
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_IMAGE = "psyb0t/rankrat";
const TRANSPORT_STDIO = "stdio";
const CONTAINER_CONFIG = "/run/config";
const CONTAINER_SECRETS = "/run/secrets";
const CONTAINER_OAUTH = "/run/oauth";
const FORWARDED_SETTINGS = [
  "RANKRAT_READ_ONLY",
  "RANKRAT_UNBOUNDED",
  "RANKRAT_ALLOW_AGENT_ONBOARDING",
  "RANKRAT_LOG_LEVEL",
];

function requiredConfigDir(environment) {
  const configDir = environment.RANKRAT_CONFIG_DIR;

  if (!configDir) {
    throw new Error(`Missing RANKRAT_CONFIG_DIR for the rankrat stdio server.

rankrat answers only for resources in its boundary file, so its directory is required:
  export RANKRAT_CONFIG_DIR=/path/to/config     # holds boundaries.json
  export RANKRAT_SECRETS_DIR=/path/to/secrets   # provider credentials, when needed
  export RANKRAT_OAUTH_DIR=/path/to/oauth       # stored Google OAuth token, when needed

See https://github.com/psyb0t/rankrat for setup.`);
  }

  return configDir;
}

/** Build the direct, hardened Docker invocation for Rankrat's stdio transport. */
export function buildDockerArgs(environment, commandArgs = []) {
  const configDir = requiredConfigDir(environment);
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

  const optionalMounts = [
    ["RANKRAT_SECRETS_DIR", CONTAINER_SECRETS],
    ["RANKRAT_OAUTH_DIR", CONTAINER_OAUTH],
  ];

  for (const [environmentName, containerPath] of optionalMounts) {
    const hostPath = environment[environmentName];
    if (hostPath) {
      args.push("--mount", `type=bind,src=${resolve(hostPath)},dst=${containerPath},readonly`);
    }
  }

  for (const setting of FORWARDED_SETTINGS) {
    if (environment[setting] !== undefined) {
      args.push("-e", `${setting}=${environment[setting]}`);
    }
  }

  args.push(environment.RANKRAT_IMAGE ?? DEFAULT_IMAGE, TRANSPORT_STDIO, ...commandArgs);
  return args;
}

/** Start Rankrat and return its exit status without handling an MCP message. */
export function runStdio(
  environment = process.env,
  commandArgs = process.argv.slice(2),
  spawn = spawnSync,
) {
  const result = spawn("docker", buildDockerArgs(environment, commandArgs), { stdio: "inherit" });

  if (result.error) {
    throw new Error(`Could not start Rankrat's stdio container: ${result.error.message}`);
  }

  return result.status ?? 1;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    process.exit(runStdio());
  } catch (error) {
    const message = error instanceof Error ? error.message : "unknown launcher failure";
    console.error(`[rankrat-mcp] ${message}`);
    process.exit(1);
  }
}
