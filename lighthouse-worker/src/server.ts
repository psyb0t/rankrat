import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { constants as filesystemConstants } from "node:fs";
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";

import {
  AUDIT_PATH,
  DEFAULT_CHROME_PATH,
  DEFAULT_RUNNER_TIMEOUT_MS,
  DEFAULT_SOCKET_PATH,
  HEALTH_PATH,
  JSON_CONTENT_TYPE,
  MAX_REQUEST_BYTES,
  MAX_RUNNER_OUTPUT_BYTES,
  MAX_RUNNER_TIMEOUT_MS,
  MAX_SOCKET_PATH_CHARS,
  MIN_RUNNER_TIMEOUT_MS,
} from "./constants.js";
import { RequestTooLargeError } from "./errors.js";
import { logger } from "./logger.js";
import { auditReportSchema, auditRequestSchema } from "./schemas.js";

const HTTP_BAD_REQUEST = 400;
const HTTP_NOT_FOUND = 404;
const HTTP_CONFLICT = 409;
const HTTP_OK = 200;
const HTTP_BAD_GATEWAY = 502;
const HTTP_UNSUPPORTED_MEDIA_TYPE = 415;
const SOCKET_MODE = 0o600;
const runnerPath = fileURLToPath(new URL("./runner.js", import.meta.url));
const runnerTimeoutSchema = z.coerce
  .number()
  .int()
  .min(MIN_RUNNER_TIMEOUT_MS)
  .max(MAX_RUNNER_TIMEOUT_MS);
const runnerTimeoutMs = runnerTimeoutSchema.parse(
  process.env.LIGHTHOUSE_RUNNER_TIMEOUT_MS ?? DEFAULT_RUNNER_TIMEOUT_MS,
);
const socketPathSchema = z
  .string()
  .min(1)
  .max(MAX_SOCKET_PATH_CHARS)
  .refine(path.isAbsolute, "Lighthouse socket path must be absolute");
const socketPath = socketPathSchema.parse(
  process.env.LIGHTHOUSE_SOCKET_PATH ?? DEFAULT_SOCKET_PATH,
);

export type AuditRunner = (input: unknown) => Promise<unknown>;

function jsonResponse(
  response: http.ServerResponse,
  status: number,
  body: unknown,
): void {
  response.writeHead(status, { "content-type": JSON_CONTENT_TYPE });
  response.end(JSON.stringify(body));
}

async function readRequestBody(request: http.IncomingMessage): Promise<Buffer> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of request as AsyncIterable<Uint8Array>) {
    const buffer = Buffer.from(chunk);
    size += buffer.length;
    if (size > MAX_REQUEST_BYTES) {
      throw new RequestTooLargeError();
    }
    chunks.push(buffer);
  }
  return Buffer.concat(chunks);
}

export async function runAudit(input: unknown): Promise<unknown> {
  const request = auditRequestSchema.parse(input);
  const child = spawn(process.execPath, [runnerPath], {
    env: { CHROME_PATH: process.env.CHROME_PATH ?? DEFAULT_CHROME_PATH },
    shell: false,
    stdio: ["pipe", "pipe", "pipe"],
  });
  return await readAuditProcess(child, request, runnerTimeoutMs);
}

export async function readAuditProcess(
  child: ChildProcessWithoutNullStreams,
  request: unknown,
  timeoutMs: number,
): Promise<unknown> {
  return await new Promise((resolve, reject) => {
    const stdout: Buffer[] = [];
    let stdoutBytes = 0;
    let stderrBytes = 0;
    let outputExceeded = false;
    let settled = false;
    const timeout = setTimeout(() => child.kill("SIGKILL"), timeoutMs);
    const rejectOnce = (error: Error): void => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timeout);
      reject(error);
    };
    child.stdout.on("data", (chunk: Buffer) => {
      stdoutBytes += chunk.length;
      if (stdoutBytes > MAX_RUNNER_OUTPUT_BYTES) {
        outputExceeded = true;
        child.kill("SIGKILL");
        return;
      }
      stdout.push(chunk);
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderrBytes += chunk.length;
      if (stderrBytes > MAX_RUNNER_OUTPUT_BYTES) {
        outputExceeded = true;
        child.kill("SIGKILL");
      }
    });
    child.once("error", (error) => {
      rejectOnce(error);
    });
    child.once("close", (code) => {
      clearTimeout(timeout);
      if (settled) {
        return;
      }
      settled = true;
      if (code !== 0 || outputExceeded) {
        reject(
          new Error(
            outputExceeded ? "runner output limit exceeded" : "runner failed",
          ),
        );
        return;
      }
      try {
        const rawReport = JSON.parse(
          Buffer.concat(stdout).toString("utf8"),
        ) as unknown;
        resolve(auditReportSchema.parse(rawReport));
      } catch (error) {
        reject(
          error instanceof Error
            ? error
            : new Error("runner response validation failed"),
        );
      }
    });
    child.stdin.end(JSON.stringify(request));
  });
}

async function handleRequest(
  request: http.IncomingMessage,
  response: http.ServerResponse,
  runAuditOperation: AuditRunner,
  state: { auditRunning: boolean },
): Promise<void> {
  if (request.method === "GET" && request.url === HEALTH_PATH) {
    jsonResponse(response, HTTP_OK, { status: "ok", busy: state.auditRunning });
    return;
  }
  if (request.method !== "POST" || request.url !== AUDIT_PATH) {
    jsonResponse(response, HTTP_NOT_FOUND, { error: "not found" });
    return;
  }
  const contentType = request.headers["content-type"];
  if (
    typeof contentType !== "string" ||
    contentType.split(";", 1)[0]?.trim().toLowerCase() !== JSON_CONTENT_TYPE
  ) {
    jsonResponse(response, HTTP_UNSUPPORTED_MEDIA_TYPE, {
      error: "application/json required",
    });
    return;
  }
  if (state.auditRunning) {
    jsonResponse(response, HTTP_CONFLICT, { error: "audit already running" });
    return;
  }
  state.auditRunning = true;
  const startedAt = performance.now();
  try {
    const body = await readRequestBody(request);
    const rawInput = JSON.parse(body.toString("utf8")) as unknown;
    const parsedInput = auditRequestSchema.parse(rawInput);
    const result = await runAuditOperation(parsedInput);
    jsonResponse(response, HTTP_OK, result);
    logger.info(
      { duration_ms: Math.round(performance.now() - startedAt) },
      "Lighthouse audit completed",
    );
  } catch (error) {
    const invalidInput =
      error instanceof SyntaxError ||
      error instanceof z.ZodError ||
      error instanceof RequestTooLargeError;
    jsonResponse(response, invalidInput ? HTTP_BAD_REQUEST : HTTP_BAD_GATEWAY, {
      error: invalidInput ? "invalid request" : "audit failed",
    });
    logger.warn(
      {
        duration_ms: Math.round(performance.now() - startedAt),
        error_kind:
          error instanceof Error ? error.constructor.name : "UnknownError",
      },
      "Lighthouse audit failed",
    );
  } finally {
    state.auditRunning = false;
  }
}

export async function prepareSocket(
  configuredSocketPath: string,
): Promise<void> {
  socketPathSchema.parse(configuredSocketPath);
  const socketDirectory = path.dirname(configuredSocketPath);
  const directory = await fs.lstat(socketDirectory);
  if (!directory.isDirectory()) {
    throw new Error(
      "configured Lighthouse socket directory is not a directory",
    );
  }
  await fs.access(
    socketDirectory,
    filesystemConstants.W_OK | filesystemConstants.X_OK,
  );
  try {
    const current = await fs.lstat(configuredSocketPath);
    if (!current.isSocket()) {
      throw new Error(
        "configured Lighthouse socket path exists and is not a socket",
      );
    }
    await fs.unlink(configuredSocketPath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      throw error;
    }
  }
}

export async function listenWorkerServer(
  server: http.Server,
  configuredSocketPath: string,
): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(configuredSocketPath, () => {
      server.off("error", reject);
      resolve();
    });
  });
  try {
    await fs.chmod(configuredSocketPath, SOCKET_MODE);
  } catch (error) {
    await new Promise<void>((resolve) => {
      server.close(() => {
        resolve();
      });
    });
    throw error;
  }
}

export function createWorkerServer(
  runAuditOperation: AuditRunner = runAudit,
): http.Server {
  const state = { auditRunning: false };
  return http.createServer((request, response) => {
    void handleRequest(request, response, runAuditOperation, state);
  });
}

async function main(): Promise<void> {
  await prepareSocket(socketPath);
  const server = createWorkerServer();
  await listenWorkerServer(server, socketPath);
  logger.info({ socket_path: socketPath }, "Lighthouse worker listening");
}

const currentModulePath = fileURLToPath(import.meta.url);
if (
  process.argv[1] !== undefined &&
  path.resolve(process.argv[1]) === currentModulePath
) {
  await main();
}
