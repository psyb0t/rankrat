import http from "node:http";

import { DEFAULT_SOCKET_PATH, HEALTH_PATH } from "./constants.js";

const HEALTH_TIMEOUT_MS = 2_000;
const HTTP_OK = 200;
const request = http.get(
  {
    socketPath: process.env.LIGHTHOUSE_SOCKET_PATH ?? DEFAULT_SOCKET_PATH,
    path: HEALTH_PATH,
  },
  (response) => {
    response.resume();
    process.exitCode = response.statusCode === HTTP_OK ? 0 : 1;
  },
);
request.setTimeout(HEALTH_TIMEOUT_MS, () => {
  request.destroy(new Error("health check timed out"));
});
request.on("error", () => {
  process.exitCode = 1;
});
