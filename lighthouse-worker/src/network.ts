import dns from "node:dns/promises";
import net from "node:net";

import { ALLOWED_DESTINATION_PORTS } from "./constants.js";

const blockedAddresses = new net.BlockList();
const globallyRoutableAddresses = new net.BlockList();

globallyRoutableAddresses.addSubnet("2000::", 3, "ipv6");

for (const [network, prefix] of [
  ["0.0.0.0", 8],
  ["10.0.0.0", 8],
  ["100.64.0.0", 10],
  ["127.0.0.0", 8],
  ["169.254.0.0", 16],
  ["172.16.0.0", 12],
  ["192.0.0.0", 24],
  ["192.0.2.0", 24],
  ["192.88.99.0", 24],
  ["192.168.0.0", 16],
  ["198.18.0.0", 15],
  ["198.51.100.0", 24],
  ["203.0.113.0", 24],
  ["224.0.0.0", 4],
  ["240.0.0.0", 4],
] as const) {
  blockedAddresses.addSubnet(network, prefix, "ipv4");
}

for (const [network, prefix] of [
  ["::", 128],
  ["::1", 128],
  ["64:ff9b::", 96],
  ["64:ff9b:1::", 48],
  ["100::", 64],
  ["100:0:0:1::", 64],
  ["2001::", 32],
  ["2001:2::", 48],
  ["2001:db8::", 32],
  ["2001:10::", 28],
  ["2002::", 16],
  ["3fff::", 20],
  ["5f00::", 16],
  ["fc00::", 7],
  ["fe80::", 10],
  ["ff00::", 8],
] as const) {
  blockedAddresses.addSubnet(network, prefix, "ipv6");
}

export interface ResolvedPublicTarget {
  readonly address: string;
  readonly family: 4 | 6;
  readonly port: number;
}

export function requireAllowedPort(port: number): void {
  if (!ALLOWED_DESTINATION_PORTS.has(port)) {
    throw new Error("destination port is not allowed");
  }
}

export function isPublicAddress(address: string, family: 4 | 6): boolean {
  if (family === 6 && address.toLowerCase().startsWith("::ffff:")) {
    return false;
  }
  const addressType = family === 4 ? "ipv4" : "ipv6";
  return (
    net.isIP(address) === family &&
    (family === 4 || globallyRoutableAddresses.check(address, "ipv6")) &&
    !blockedAddresses.check(address, addressType)
  );
}

export async function resolvePublicTarget(
  hostname: string,
  port: number,
): Promise<ResolvedPublicTarget> {
  requireAllowedPort(port);
  if (!hostname || hostname.includes("%")) {
    throw new Error("destination hostname is invalid");
  }
  const answers = await dns.lookup(hostname, { all: true, verbatim: true });
  if (answers.length === 0) {
    throw new Error("destination did not resolve");
  }
  if (
    answers.some(
      (answer) =>
        (answer.family !== 4 && answer.family !== 6) ||
        !isPublicAddress(answer.address, answer.family),
    )
  ) {
    throw new Error("destination resolves to a non-public address");
  }
  const selected = answers[0];
  if (selected === undefined) {
    throw new Error("destination did not resolve");
  }
  if (selected.family !== 4 && selected.family !== 6) {
    throw new Error("destination resolved to an unsupported address family");
  }
  return { address: selected.address, family: selected.family, port };
}
