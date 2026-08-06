export const AUDIT_PATH = "/v1/audits";
export const HEALTH_PATH = "/healthz";
export const JSON_CONTENT_TYPE = "application/json";
export const MAX_REQUEST_BYTES = 65_536;
export const MAX_RUNNER_OUTPUT_BYTES = 2_097_152;
export const DEFAULT_RUNNER_TIMEOUT_MS = 120_000;
export const MIN_RUNNER_TIMEOUT_MS = 5_000;
export const MAX_RUNNER_TIMEOUT_MS = 300_000;
export const DEFAULT_SOCKET_PATH = "/run/lighthouse/lighthouse.sock";
export const DEFAULT_CHROME_PATH = "/opt/chrome/chrome";
export const MAX_FINDINGS = 500;
export const MAX_ID_CHARS = 128;
export const MAX_TITLE_CHARS = 256;
export const MAX_DESCRIPTION_CHARS = 4_096;
export const MAX_DISPLAY_VALUE_CHARS = 1_024;
export const MAX_SOCKET_PATH_CHARS = 4_096;
export const ALLOWED_DESTINATION_PORTS = new Set([80, 443]);

export const LIGHTHOUSE_CATEGORIES = [
  "performance",
  "accessibility",
  "best-practices",
  "seo",
] as const;

export type LighthouseCategory = (typeof LIGHTHOUSE_CATEGORIES)[number];
