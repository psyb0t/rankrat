#!/usr/bin/env node
// This is an MCP stdio launcher, not an OpenClaw extension. Its stdout belongs
// exclusively to the Rankrat container's MCP protocol; launcher failures use
// stderr so they cannot corrupt the protocol stream.
import { spawnSync } from "node:child_process";
import { lstatSync, realpathSync } from "node:fs";
import { isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_IMAGE = "psyb0t/rankrat";
const DEFAULT_READ_ONLY = "false";
const TRANSPORT_STDIO = "stdio";
const CONTAINER_CONFIG = "/run/config";
const CONTAINER_SECRETS = "/run/secrets";
const CONTAINER_OAUTH = "/run/oauth";
const CONTAINER_STATE = "/run/state";
const CONTAINER_STATE_DATABASE = "/run/state/rankrat.sqlite3";
const BOUNDARY_FILE_NAME = "boundaries.json";
const STANDARD_DATA_ROOT_PARTS = [".config", "rankrat"];
const STANDARD_CONFIG_DIR_NAME = "config";
const STANDARD_SECRETS_DIR_NAME = "secrets";
const STANDARD_OAUTH_DIR_NAME = "oauth";
const STANDARD_STATE_DIR_NAME = "state";
const FORBIDDEN_MOUNT_PATH_CHARACTERS = /[\r\n,]/u;
const TRUE = "true";
const FALSE = "false";
const POSIX_GROUP_AND_OTHER_WRITE_BITS = 0o022;
const POSIX_GROUP_AND_OTHER_ANY_BITS = 0o077;
const PIDS_LIMIT = "128";
const MEMORY_LIMIT = "512m";
const CPU_LIMIT = "1";
const FORWARDED_SETTINGS = [
  "RANKRAT_READ_ONLY",
  "RANKRAT_LOG_LEVEL",
];

function requiredDataDirectory(environment) {
  const configuredDirectory = environment.RANKRAT_DATA_DIR;
  const dataDirectory = configuredDirectory || standardDataRoot(environment);
  if (!isAbsolute(dataDirectory)) {
    throw new Error("RANKRAT_DATA_DIR must be an absolute path");
  }
  if (FORBIDDEN_MOUNT_PATH_CHARACTERS.test(dataDirectory)) {
    throw new Error(
      "RANKRAT_DATA_DIR contains a forbidden mount delimiter or line break",
    );
  }

  const normalizedDataDirectory =
    dataDirectory === "/" ? dataDirectory : dataDirectory.replace(/\/+$/u, "");
  if (normalizedDataDirectory === "/") {
    throw new Error("RANKRAT_DATA_DIR must not be the filesystem root");
  }
  const resolvedDataDirectory = resolve(normalizedDataDirectory);
  if (resolvedDataDirectory !== normalizedDataDirectory) {
    throw new Error(
      "RANKRAT_DATA_DIR must be canonical and contain no symbolic links",
    );
  }
  requireDirectory(resolvedDataDirectory, "RANKRAT_DATA_DIR");
  return resolvedDataDirectory;
}

function standardDataRoot(environment) {
  const homeDirectory = environment.HOME;
  if (!homeDirectory) {
    throw new Error(
      "Missing HOME; OpenClaw's default Rankrat layout is $HOME/.config/rankrat",
    );
  }
  return resolve(homeDirectory, ...STANDARD_DATA_ROOT_PARTS);
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
  const directoryInformation = pathInformation(
    configDir,
    "Rankrat config directory",
  );
  const boundaryInformation = pathInformation(boundaryFile, boundaryFile);
  const userID = process.getuid();

  if ((directoryInformation.mode & POSIX_GROUP_AND_OTHER_ANY_BITS) !== 0) {
    throw new Error(
      `Rankrat config directory must be owner-only; run chmod 700 ${configDir}`,
    );
  }
  if ((boundaryInformation.mode & POSIX_GROUP_AND_OTHER_WRITE_BITS) !== 0) {
    throw new Error(`${boundaryFile} must not be group- or world-writable`);
  }
  if (directoryInformation.uid !== userID || boundaryInformation.uid !== userID) {
    throw new Error(
      `Rankrat config directory and boundaries.json must be owned by UID ${userID}`,
    );
  }
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
  const dataDirectory = requiredDataDirectory(environment);
  const configDir = resolve(dataDirectory, STANDARD_CONFIG_DIR_NAME);
  const secretsDir = resolve(dataDirectory, STANDARD_SECRETS_DIR_NAME);
  const oauthDir = resolve(dataDirectory, STANDARD_OAUTH_DIR_NAME);
  const stateDir = resolve(dataDirectory, STANDARD_STATE_DIR_NAME);
  requireDirectory(configDir, "Rankrat config directory");
  requireDirectory(secretsDir, "Rankrat secrets directory");
  requireDirectory(oauthDir, "Rankrat OAuth directory");
  requireDirectory(stateDir, "Rankrat state directory");
  requireRegularFile(
    resolve(configDir, BOUNDARY_FILE_NAME),
    "Rankrat boundary file",
  );
  const readOnly = booleanSetting(
    environment,
    "RANKRAT_READ_ONLY",
    DEFAULT_READ_ONLY,
  );
  const writableConfig = !readOnly;
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

  args.push(
    "--mount",
    `type=bind,src=${secretsDir},dst=${CONTAINER_SECRETS},readonly`,
    "--mount",
    `type=bind,src=${oauthDir},dst=${CONTAINER_OAUTH}`,
    "--mount",
    `type=bind,src=${stateDir},dst=${CONTAINER_STATE}`,
    "-e",
    `RANKRAT_STATE_DATABASE=${CONTAINER_STATE_DATABASE}`,
  );

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
