import * as chromeLauncher from "chrome-launcher";
import lighthouse from "lighthouse";

import { DEFAULT_CHROME_PATH } from "./constants.js";
import { startSafeProxy } from "./proxy.js";
import { reportFromResult } from "./report.js";
import { auditRequestSchema } from "./schemas.js";

async function readStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin as AsyncIterable<Uint8Array>) {
    chunks.push(Buffer.from(chunk));
  }
  return Buffer.concat(chunks).toString("utf8");
}

async function main(): Promise<void> {
  const input = JSON.parse(await readStdin()) as unknown;
  const request = auditRequestSchema.parse(input);
  const proxy = await startSafeProxy();
  const chrome = await chromeLauncher.launch({
    chromePath: process.env.CHROME_PATH ?? DEFAULT_CHROME_PATH,
    chromeFlags: [
      "--headless=new",
      "--disable-background-networking",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      "--disable-quic",
      "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
      "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
      "--no-sandbox",
      `--proxy-server=${proxy.url}`,
      "--proxy-bypass-list=<-loopback>",
    ],
  });
  try {
    const result = await lighthouse(request.url, {
      logLevel: "silent",
      output: "json",
      onlyCategories: request.categories,
      port: chrome.port,
    });
    if (result === undefined) {
      throw new Error("Lighthouse returned no result");
    }
    process.stdout.write(
      JSON.stringify(reportFromResult(result, request.categories)),
    );
  } finally {
    chrome.kill();
    await proxy.close();
  }
}

await main();
