import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import {
  MAX_REQUEST_BYTES,
  MAX_RUNNER_OUTPUT_BYTES,
} from "../src/constants.js";
import {
  createWorkerServer,
  listenWorkerServer,
  prepareSocket,
  readAuditProcess,
  type AuditRunner,
} from "../src/server.js";

const REPORT = {
  requestedUrl: "https://example.com/",
  finalUrl: "https://example.com/",
  fetchTime: "2026-08-05T18:30:32.000Z",
  lighthouseVersion: "13.4.1",
  categories: { seo: { score: 1 } },
  findings: [],
};

let cleanup: (() => Promise<void>) | undefined;

afterEach(async () => {
  await cleanup?.();
  cleanup = undefined;
});

async function startServer(runner: AuditRunner): Promise<string> {
  const directory = await fs.mkdtemp(
    path.join(os.tmpdir(), "rankrat-lighthouse-"),
  );
  const socketPath = path.join(directory, "worker.sock");
  const server = createWorkerServer(runner);
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(socketPath, () => {
      server.off("error", reject);
      resolve();
    });
  });
  cleanup = async () => {
    await new Promise<void>((resolve, reject) => {
      server.close((error) => {
        if (error === undefined) {
          resolve();
          return;
        }
        reject(error);
      });
    });
    await fs.rm(directory, { recursive: true });
  };
  return socketPath;
}

async function request(
  socketPath: string,
  body: string,
  contentType: string | null = "application/json",
): Promise<{ status: number | undefined; body: string }> {
  return await new Promise((resolve, reject) => {
    const call = http.request(
      {
        socketPath,
        method: "POST",
        path: "/v1/audits",
        headers: contentType === null ? {} : { "content-type": contentType },
      },
      (response) => {
        const chunks: Buffer[] = [];
        response.on("data", (chunk: Buffer) => chunks.push(chunk));
        response.on("end", () => {
          resolve({
            status: response.statusCode,
            body: Buffer.concat(chunks).toString("utf8"),
          });
        });
      },
    );
    call.on("error", reject);
    call.end(body);
  });
}

describe("Lighthouse worker server", () => {
  it("returns a validated deterministic report over a Unix socket", async () => {
    const socketPath = await startServer(() => Promise.resolve(REPORT));

    const response = await request(
      socketPath,
      JSON.stringify({ url: "https://example.com/", categories: ["seo"] }),
    );

    expect(response.status).toBe(200);
    expect(JSON.parse(response.body)).toEqual(REPORT);
  });

  it.each([null, "text/plain", "application/xml"])(
    "rejects a non-JSON content type (%s)",
    async (contentType) => {
      const socketPath = await startServer(() => Promise.resolve(REPORT));

      const response = await request(
        socketPath,
        JSON.stringify({ url: "https://example.com/", categories: ["seo"] }),
        contentType,
      );

      expect(response.status).toBe(415);
      expect(JSON.parse(response.body)).toEqual({
        error: "application/json required",
      });
    },
  );

  it("accepts the JSON media type with a charset parameter", async () => {
    const socketPath = await startServer(() => Promise.resolve(REPORT));

    const response = await request(
      socketPath,
      JSON.stringify({ url: "https://example.com/", categories: ["seo"] }),
      "Application/JSON; charset=utf-8",
    );

    expect(response.status).toBe(200);
  });

  it.each([
    "not-json",
    JSON.stringify({ url: "http://example.com/", categories: ["seo"] }),
    JSON.stringify({
      url: "https://example.com/",
      categories: ["seo"],
      command: "id",
    }),
    "x".repeat(MAX_REQUEST_BYTES + 1),
  ])("rejects malformed, over-posted, and oversized input", async (body) => {
    const socketPath = await startServer(() => Promise.resolve(REPORT));

    const response = await request(socketPath, body);

    expect(response.status).toBe(400);
    expect(JSON.parse(response.body)).toEqual({ error: "invalid request" });
  });

  it("rejects a concurrent expensive audit and recovers after completion", async () => {
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const socketPath = await startServer(async () => {
      await gate;
      return REPORT;
    });
    const body = JSON.stringify({
      url: "https://example.com/",
      categories: ["seo"],
    });

    const first = request(socketPath, body);
    await new Promise((resolve) => setTimeout(resolve, 10));
    const busy = await request(socketPath, body);
    release?.();
    const completed = await first;
    const next = await request(socketPath, body);

    expect(busy.status).toBe(409);
    expect(completed.status).toBe(200);
    expect(next.status).toBe(200);
  });

  it("returns a finite error when the runner fails", async () => {
    const socketPath = await startServer(() =>
      Promise.reject(new Error("raw subprocess output must not escape")),
    );

    const response = await request(
      socketPath,
      JSON.stringify({ url: "https://example.com/", categories: ["seo"] }),
    );

    expect(response.status).toBe(502);
    expect(JSON.parse(response.body)).toEqual({ error: "audit failed" });
    expect(response.body).not.toContain("raw subprocess output");
  });
});

describe("Lighthouse worker socket", () => {
  it("requires an existing directory and restricts the listening socket", async () => {
    const directory = await fs.mkdtemp(
      path.join(os.tmpdir(), "rankrat-lighthouse-socket-"),
    );
    const socketPath = path.join(directory, "worker.sock");
    const server = createWorkerServer(() => Promise.resolve(REPORT));
    try {
      await prepareSocket(socketPath);
      await listenWorkerServer(server, socketPath);

      const current = await fs.lstat(socketPath);
      expect(current.isSocket()).toBe(true);
      expect(current.mode & 0o777).toBe(0o600);
    } finally {
      await new Promise<void>((resolve) => {
        server.close(() => {
          resolve();
        });
      });
      await fs.rm(directory, { recursive: true });
    }
  });

  it("rejects a missing socket directory", async () => {
    const directory = await fs.mkdtemp(
      path.join(os.tmpdir(), "rankrat-lighthouse-socket-"),
    );
    try {
      await expect(
        prepareSocket(path.join(directory, "missing", "worker.sock")),
      ).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await fs.rm(directory, { recursive: true });
    }
  });

  it("rejects a relative socket path", async () => {
    await expect(prepareSocket("relative/worker.sock")).rejects.toThrow(
      "Lighthouse socket path must be absolute",
    );
  });

  it.each(["file", "symlink"])("rejects an existing %s", async (kind) => {
    const directory = await fs.mkdtemp(
      path.join(os.tmpdir(), "rankrat-lighthouse-socket-"),
    );
    const socketPath = path.join(directory, "worker.sock");
    try {
      if (kind === "file") {
        await fs.writeFile(socketPath, "occupied", "utf8");
      } else {
        await fs.symlink(path.join(directory, "missing"), socketPath);
      }

      await expect(prepareSocket(socketPath)).rejects.toThrow(
        "exists and is not a socket",
      );
    } finally {
      await fs.rm(directory, { recursive: true });
    }
  });
});

describe("bounded Lighthouse runner process", () => {
  it("parses a validated report from a real child process", async () => {
    const child = spawn(
      process.execPath,
      [
        "-e",
        `process.stdin.resume(); process.stdin.on("end", () => process.stdout.write(${JSON.stringify(JSON.stringify(REPORT))}))`,
      ],
      { stdio: ["pipe", "pipe", "pipe"] },
    );

    await expect(readAuditProcess(child, {}, 1_000)).resolves.toEqual(REPORT);
  });

  it.each([
    [
      "nonzero exit",
      'process.stderr.write("secret stderr"); process.exit(1)',
      "runner failed",
    ],
    ["empty output", "", "Unexpected end of JSON input"],
    [
      "malformed output",
      'process.stdout.write("not-json")',
      "Unexpected token",
    ],
  ])("rejects %s without reflecting stderr", async (_name, script, message) => {
    const child = spawn(process.execPath, ["-e", script], {
      stdio: ["pipe", "pipe", "pipe"],
    });

    await expect(readAuditProcess(child, {}, 1_000)).rejects.toThrow(message);
  });

  it("kills a runner that exceeds the output limit", async () => {
    const child = spawn(
      process.execPath,
      [
        "-e",
        `process.stdout.write("x".repeat(${String(MAX_RUNNER_OUTPUT_BYTES + 1)}))`,
      ],
      { stdio: ["pipe", "pipe", "pipe"] },
    );

    await expect(readAuditProcess(child, {}, 1_000)).rejects.toThrow(
      "runner output limit exceeded",
    );
  });

  it("kills a runner that exceeds its deadline", async () => {
    const child = spawn(
      process.execPath,
      ["-e", "setInterval(() => {}, 1000)"],
      {
        stdio: ["pipe", "pipe", "pipe"],
      },
    );

    await expect(readAuditProcess(child, {}, 10)).rejects.toThrow(
      "runner failed",
    );
  });
});
