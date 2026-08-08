#!/usr/bin/env node
// This is an MCP stdio launcher, not an OpenClaw extension. Its stdout belongs
// exclusively to the Rankrat container's MCP protocol; launcher failures use
// stderr so they cannot corrupt the protocol stream.
import { spawnSync } from "node:child_process";
import { existsSync, lstatSync, realpathSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_IMAGE = "psyb0t/rankrat";
const DEFAULT_READ_ONLY = "true";
const DEFAULT_UNBOUNDED = "false";
const DEFAULT_AGENT_ONBOARDING = "false";
const TRANSPORT_STDIO = "stdio";
const CONTAINER_CONFIG = "/run/config";
const CONTAINER_SECRETS = "/run/secrets";
const CONTAINER_OAUTH = "/run/oauth";
const CONTAINER_STATE = "/run/state";
const CONTAINER_STATE_DATABASE = "/run/state/rankrat.sqlite3";
const BOUNDARY_FILE_NAME = "boundaries.json";
const STANDARD_CONFIG_ROOT_PARTS = [".config", "rankrat"];
const STANDARD_CONFIG_DIR_NAME = "config";
const STANDARD_SECRETS_DIR_NAME = "secrets";
const STANDARD_OAUTH_DIR_NAME = "oauth";
const STANDARD_STATE_DIR_NAME = "state";
const TRUE = "true";
const FALSE = "false";
const POSIX_GROUP_AND_OTHER_WRITE_BITS = 0o022;
const POSIX_GROUP_AND_OTHER_ANY_BITS = 0o077;
const PIDS_LIMIT = "128";
const MEMORY_LIMIT = "512m";
const CPU_LIMIT = "1";
const FORWARDED_SETTINGS = [
  "RANKRAT_READ_ONLY",
  "RANKRAT_UNBOUNDED",
  "RANKRAT_ALLOW_AGENT_ONBOARDING",
  "RANKRAT_LOG_LEVEL",
];

function requiredConfigDir(environment) {
  const configDir =
    environment.RANKRAT_CONFIG_DIR ??
    resolve(standardConfigRoot(environment), STANDARD_CONFIG_DIR_NAME);

  if (!configDir) {
    throw new Error(`Missing RANKRAT_CONFIG_DIR for the rankrat stdio server.

rankrat answers only for resources in its boundary file, so its directory is required:
  export RANKRAT_CONFIG_DIR=/path/to/config     # holds boundaries.json
  export RANKRAT_SECRETS_DIR=/path/to/secrets   # provider credentials, when needed
  export RANKRAT_OAUTH_DIR=/path/to/oauth       # stored Google OAuth token, when needed

See https://github.com/psyb0t/rankrat for setup.`);
  }

  const resolvedConfigDir = resolve(configDir);
  const configDescription = environment.RANKRAT_CONFIG_DIR
    ? "RANKRAT_CONFIG_DIR"
    : "default Rankrat config directory";
  requireDirectory(resolvedConfigDir, configDescription);
  requireRegularFile(
    resolve(resolvedConfigDir, BOUNDARY_FILE_NAME),
    `${resolvedConfigDir}/${BOUNDARY_FILE_NAME}`,
  );
  return resolvedConfigDir;
}

function standardConfigRoot(environment) {
  const homeDirectory = environment.HOME;
  if (!homeDirectory) {
    throw new Error(
      "Missing HOME; OpenClaw's default Rankrat layout is $HOME/.config/rankrat",
    );
  }
  return resolve(homeDirectory, ...STANDARD_CONFIG_ROOT_PARTS);
}

function requireDirectory(path, description) {
  const information = pathInformation(path, description);
  if (!information.isDirectory()) {
    throw new Error(`${description} must be a directory: ${path}`);
  }
}

function requireRegularFile(path, description) {
  const information = pathInformation(path, description);
  if (!information.isFile()) {
    throw new Error(`${description} must be a regular file: ${path}`);
  }
}

function pathInformation(path, description) {
  let information;
  let canonicalPath;
  try {
    canonicalPath = realpathSync(path);
    information = lstatSync(path);
  } catch (error) {
    const reason =
      error instanceof Error ? error.message : "unknown filesystem error";
    throw new Error(`${description} is not accessible: ${reason}`, {
      cause: error,
    });
  }

  if (canonicalPath !== path) {
    throw new Error(`${description} must not contain symbolic links: ${path}`);
  }

  if (information.isSymbolicLink()) {
    throw new Error(`${description} must not be a symbolic link: ${path}`);
  }
  return information;
}

function booleanSetting(environment, name, defaultValue) {
  const value = environment[name] ?? defaultValue;
  if (value !== TRUE && value !== FALSE) {
    throw new Error(`${name} must be either true or false, got '${value}'`);
  }
  return value === TRUE;
}

function requireWritableBoundaryIsSafe(configDir) {
  if (typeof process.getuid !== "function") {
    throw new Error(
      "Writable boundary persistence requires a POSIX host with UID ownership checks",
    );
  }

  const boundaryFile = resolve(configDir, BOUNDARY_FILE_NAME);
  const directoryInformation = pathInformation(configDir, "RANKRAT_CONFIG_DIR");
  const boundaryInformation = pathInformation(boundaryFile, boundaryFile);
  const userID = process.getuid();

  if ((directoryInformation.mode & POSIX_GROUP_AND_OTHER_ANY_BITS) !== 0) {
    throw new Error(
      `RANKRAT_CONFIG_DIR must be owner-only; run chmod 700 ${configDir}`,
    );
  }
  if ((boundaryInformation.mode & POSIX_GROUP_AND_OTHER_WRITE_BITS) !== 0) {
    throw new Error(`${boundaryFile} must not be group- or world-writable`);
  }
  if (directoryInformation.uid !== userID || boundaryInformation.uid !== userID) {
    throw new Error(
      `RANKRAT_CONFIG_DIR and boundaries.json must be owned by UID ${userID}`,
    );
  }
}

function optionalMountDirectory(environment, environmentName, defaultDirectory) {
  const configuredPath = environment[environmentName];
  const hostPath = configuredPath ?? defaultDirectory;
  if (!hostPath) {
    return undefined;
  }
  if (!configuredPath && !existsSync(hostPath)) {
    return undefined;
  }
  const resolvedHostPath = resolve(hostPath);
  requireDirectory(resolvedHostPath, environmentName);
  return resolvedHostPath;
}

function currentUserArgument() {
  if (
    typeof process.getuid !== "function" ||
    typeof process.getgid !== "function"
  ) {
    return [];
  }
  return ["--user", `${process.getuid()}:${process.getgid()}`];
}

/** Build the direct, hardened Docker invocation for Rankrat's stdio transport. */
export function buildDockerArgs(environment, commandArgs = []) {
  const configDir = requiredConfigDir(environment);
  const readOnly = booleanSetting(
    environment,
    "RANKRAT_READ_ONLY",
    DEFAULT_READ_ONLY,
  );
  const unbounded = booleanSetting(
    environment,
    "RANKRAT_UNBOUNDED",
    DEFAULT_UNBOUNDED,
  );
  const allowAgentOnboarding = booleanSetting(
    environment,
    "RANKRAT_ALLOW_AGENT_ONBOARDING",
    DEFAULT_AGENT_ONBOARDING,
  );

  if (unbounded && readOnly) {
    throw new Error("RANKRAT_UNBOUNDED=true requires RANKRAT_READ_ONLY=false");
  }
  if (allowAgentOnboarding && readOnly) {
    throw new Error(
      "RANKRAT_ALLOW_AGENT_ONBOARDING=true requires RANKRAT_READ_ONLY=false",
    );
  }
  const writableConfig = unbounded || allowAgentOnboarding;
  if (writableConfig) {
    requireWritableBoundaryIsSafe(configDir);
  }

  const configMount = `type=bind,src=${configDir},dst=${CONTAINER_CONFIG}${
    writableConfig ? "" : ",readonly"
  }`;
  const args = [
    "run",
    "--rm",
    "-i",
    "--init",
    ...currentUserArgument(),
    "--read-only",
    "--cap-drop=ALL",
    "--security-opt",
    "no-new-privileges:true",
    "--pids-limit",
    PIDS_LIMIT,
    "--memory",
    MEMORY_LIMIT,
    "--cpus",
    CPU_LIMIT,
    "--tmpfs",
    "/tmp:rw,noexec,nosuid,size=32m",
    "--mount",
    configMount,
  ];

  const standardRoot = environment.HOME
    ? standardConfigRoot(environment)
    : undefined;
  const optionalMounts = [
    [
      "RANKRAT_SECRETS_DIR",
      standardRoot ? resolve(standardRoot, STANDARD_SECRETS_DIR_NAME) : undefined,
      CONTAINER_SECRETS,
    ],
    [
      "RANKRAT_OAUTH_DIR",
      standardRoot ? resolve(standardRoot, STANDARD_OAUTH_DIR_NAME) : undefined,
      CONTAINER_OAUTH,
    ],
    [
      "RANKRAT_STATE_DIR",
      standardRoot ? resolve(standardRoot, STANDARD_STATE_DIR_NAME) : undefined,
      CONTAINER_STATE,
    ],
  ];

  for (const [
    environmentName,
    defaultDirectory,
    containerPath,
  ] of optionalMounts) {
    const resolvedHostPath = optionalMountDirectory(
      environment,
      environmentName,
      defaultDirectory,
    );
    if (resolvedHostPath) {
      const readOnlySuffix =
        containerPath === CONTAINER_SECRETS ? ",readonly" : "";
      args.push(
        "--mount",
        `type=bind,src=${resolvedHostPath},dst=${containerPath}${readOnlySuffix}`,
      );
      if (containerPath === CONTAINER_STATE) {
        args.push("-e", `RANKRAT_STATE_DATABASE=${CONTAINER_STATE_DATABASE}`);
      }
    }
  }

  for (const setting of FORWARDED_SETTINGS) {
    if (environment[setting] !== undefined) {
      args.push("-e", `${setting}=${environment[setting]}`);
    }
  }

  args.push(
    environment.RANKRAT_IMAGE ?? DEFAULT_IMAGE,
    TRANSPORT_STDIO,
    ...commandArgs,
  );
  return args;
}

/** Start Rankrat and return its exit status without handling an MCP message. */
export function runStdio(
  environment = process.env,
  commandArgs = process.argv.slice(2),
  spawn = spawnSync,
) {
  const result = spawn("docker", buildDockerArgs(environment, commandArgs), {
    stdio: "inherit",
  });

  if (result.error) {
    throw new Error(
      `Could not start Rankrat's stdio container: ${result.error.message}`,
    );
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
