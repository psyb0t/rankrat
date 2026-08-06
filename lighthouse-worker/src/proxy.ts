import http, { type IncomingHttpHeaders } from "node:http";
import net from "node:net";
import type { Duplex } from "node:stream";

import { resolvePublicTarget } from "./network.js";

const PROXY_LISTEN_HOST = "127.0.0.1";
const HTTP_PORT = 80;
const HTTPS_PORT = 443;
const BAD_GATEWAY_STATUS = 502;
const FORBIDDEN_STATUS = 403;

export interface SafeProxy {
  readonly url: string;
  close(): Promise<void>;
}

function outboundHeaders(
  headers: IncomingHttpHeaders,
  authority: string,
): IncomingHttpHeaders {
  const safeHeaders: IncomingHttpHeaders = { ...headers, host: authority };
  delete safeHeaders["proxy-authorization"];
  delete safeHeaders["proxy-connection"];
  return safeHeaders;
}

export async function startSafeProxy(): Promise<SafeProxy> {
  const server = http.createServer((request, response) => {
    void handleHttpRequest(request, response);
  });
  server.on("connect", (request, clientSocket, head) => {
    void handleConnect(request, clientSocket, head);
  });
  server.on("clientError", (_error, socket) => {
    socket.end("HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n");
  });

  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, PROXY_LISTEN_HOST, () => {
      server.off("error", reject);
      resolve();
    });
  });
  const address = server.address();
  if (address === null || typeof address === "string") {
    throw new Error("proxy did not bind a TCP port");
  }
  return {
    url: `http://${PROXY_LISTEN_HOST}:${String(address.port)}`,
    close: () =>
      new Promise<void>((resolve, reject) => {
        server.close((error) => {
          if (error === undefined) {
            resolve();
            return;
          }
          reject(error);
        });
      }),
  };
}

async function handleHttpRequest(
  request: http.IncomingMessage,
  response: http.ServerResponse,
): Promise<void> {
  try {
    const target = new URL(request.url ?? "");
    if (target.protocol !== "http:") {
      throw new Error("plain proxy requests must use HTTP");
    }
    const port = target.port ? Number.parseInt(target.port, 10) : HTTP_PORT;
    const resolved = await resolvePublicTarget(target.hostname, port);
    const upstream = http.request(
      {
        family: resolved.family,
        headers: outboundHeaders(request.headers, target.host),
        host: resolved.address,
        method: request.method,
        path: `${target.pathname}${target.search}`,
        port: resolved.port,
      },
      (upstreamResponse) => {
        response.writeHead(
          upstreamResponse.statusCode ?? BAD_GATEWAY_STATUS,
          upstreamResponse.headers,
        );
        upstreamResponse.pipe(response);
      },
    );
    upstream.on("error", () => response.destroy());
    request.pipe(upstream);
  } catch {
    response.writeHead(FORBIDDEN_STATUS, { connection: "close" });
    response.end();
  }
}

async function handleConnect(
  request: http.IncomingMessage,
  clientSocket: Duplex,
  head: Buffer,
): Promise<void> {
  try {
    const authority = new URL(`https://${request.url ?? ""}`);
    const port = authority.port
      ? Number.parseInt(authority.port, 10)
      : HTTPS_PORT;
    const resolved = await resolvePublicTarget(authority.hostname, port);
    const upstream = net.connect({
      host: resolved.address,
      port: resolved.port,
      family: resolved.family,
    });
    bridgeConnectTunnel(clientSocket, upstream, head);
  } catch {
    clientSocket.end("HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n");
  }
}

export function bridgeConnectTunnel(
  clientSocket: Duplex,
  upstream: Duplex,
  head: Buffer,
): void {
  clientSocket.once("error", () => upstream.destroy());
  upstream.once("error", () => clientSocket.destroy());
  upstream.once("connect", () => {
    clientSocket.write("HTTP/1.1 200 Connection Established\r\n\r\n");
    if (head.length > 0) {
      upstream.write(head);
    }
    upstream.pipe(clientSocket);
    clientSocket.pipe(upstream);
  });
}
