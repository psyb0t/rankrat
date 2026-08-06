import http from "node:http";
import net from "node:net";
import { PassThrough } from "node:stream";

import { afterEach, describe, expect, it } from "vitest";

import { isPublicAddress, requireAllowedPort } from "../src/network.js";
import {
  bridgeConnectTunnel,
  startSafeProxy,
  type SafeProxy,
} from "../src/proxy.js";
import { auditRequestSchema } from "../src/schemas.js";

let proxy: SafeProxy | undefined;

afterEach(async () => {
  await proxy?.close();
  proxy = undefined;
});

describe("public destination policy", () => {
  it.each([
    ["127.0.0.1", 4],
    ["10.0.0.1", 4],
    ["169.254.169.254", 4],
    ["192.0.2.1", 4],
    ["::1", 6],
    ["::ffff:127.0.0.1", 6],
    ["64:ff9b:1::1", 6],
    ["100:0:0:1::1", 6],
    ["2001::1", 6],
    ["2001:2::1", 6],
    ["2002::1", 6],
    ["3fff::1", 6],
    ["4000::1", 6],
    ["5f00::1", 6],
    ["fc00::1", 6],
    ["fe80::1", 6],
  ] as const)("rejects non-public address %s", (address, family) => {
    expect(isPublicAddress(address, family)).toBe(false);
  });

  it("accepts public addresses and only web ports", () => {
    expect(isPublicAddress("1.1.1.1", 4)).toBe(true);
    expect(isPublicAddress("2606:4700:4700::1111", 6)).toBe(true);
    expect(() => {
      requireAllowedPort(80);
    }).not.toThrow();
    expect(() => {
      requireAllowedPort(443);
    }).not.toThrow();
    expect(() => {
      requireAllowedPort(22);
    }).toThrow("destination port is not allowed");
  });

  it("blocks loopback requests through the real proxy", async () => {
    proxy = await startSafeProxy();
    const proxyUrl = new URL(proxy.url);
    const status = await new Promise<number | undefined>((resolve, reject) => {
      const request = http.request(
        {
          host: proxyUrl.hostname,
          port: proxyUrl.port,
          method: "GET",
          path: "http://127.0.0.1/private",
        },
        (response) => {
          response.resume();
          resolve(response.statusCode);
        },
      );
      request.on("error", reject);
      request.end();
    });

    expect(status).toBe(403);
  });

  it("blocks loopback CONNECT tunnels through the real proxy", async () => {
    proxy = await startSafeProxy();
    const proxyUrl = new URL(proxy.url);
    const statusLine = await new Promise<string>((resolve, reject) => {
      const socket = net.connect({
        host: proxyUrl.hostname,
        port: Number.parseInt(proxyUrl.port, 10),
      });
      socket.setEncoding("utf8");
      socket.once("connect", () => {
        socket.write(
          "CONNECT 127.0.0.1:443 HTTP/1.1\r\nHost: 127.0.0.1:443\r\n\r\n",
        );
      });
      socket.once("data", (data: string) => {
        resolve(data.split("\r\n", 1)[0] ?? "");
        socket.destroy();
      });
      socket.once("error", reject);
    });

    expect(statusLine).toBe("HTTP/1.1 403 Forbidden");
  });

  it("absorbs an early client tunnel error and destroys the upstream", () => {
    const client = new PassThrough();
    const upstream = new PassThrough();
    bridgeConnectTunnel(client, upstream, Buffer.alloc(0));
    upstream.emit("connect");

    client.emit("error", new Error("simulated EPIPE"));

    expect(upstream.destroyed).toBe(true);
  });
});

describe("audit request schema", () => {
  it("accepts fixed HTTPS categories", () => {
    expect(
      auditRequestSchema.parse({
        url: "https://example.com/page",
        categories: ["performance", "seo"],
      }),
    ).toEqual({
      url: "https://example.com/page",
      categories: ["performance", "seo"],
    });
  });

  it.each([
    { url: "http://example.com", categories: ["seo"] },
    { url: "https://user:password@example.com", categories: ["seo"] },
    { url: "https://example.com:8443", categories: ["seo"] },
    { url: "https://example.com/page#fragment", categories: ["seo"] },
    { url: "https://example.com", categories: [] },
    { url: "https://example.com", categories: ["seo", "seo"] },
    { url: "https://example.com", categories: ["unknown"] },
    { url: "https://example.com", categories: ["seo"], command: "whoami" },
  ])("rejects malformed or over-posted requests", (request) => {
    expect(auditRequestSchema.safeParse(request).success).toBe(false);
  });
});
