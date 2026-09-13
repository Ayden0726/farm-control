/** Normalize Settings → Public domain. Keep in sync with backend/app/services/public_host.py. */

export type PublicHost = {
  raw: string;
  host: string;
  origin: string;
  error: string;
};

const JUNK =
  "That doesn’t look like a domain or IP. Try example.com, farm.example.com, or a LAN address.";

const LABEL = /^(?:xn--)?[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/i;

export function normalizePublicHost(raw: string | null | undefined): PublicHost {
  const text = (raw || "").trim();
  if (!text) return { raw: "", host: "", origin: "", error: "" };
  if (/\s/.test(text)) {
    return {
      raw: text,
      host: "",
      origin: "",
      error: "Domain cannot contain spaces. Use example.com or farm.example.com.",
    };
  }
  if (/[\\<>"'`@]/.test(text)) {
    return { raw: text, host: "", origin: "", error: JUNK };
  }

  let schemeIn = "";
  let hostname = "";
  let port: number | null = null;
  try {
    const parsed = parseInput(text);
    schemeIn = parsed.scheme;
    hostname = parsed.hostname;
    port = parsed.port;
  } catch (err) {
    return { raw: text, host: "", origin: "", error: err instanceof Error ? err.message : JUNK };
  }

  hostname = hostname.replace(/\.+$/, "").toLowerCase();
  if (!hostname) return { raw: text, host: "", origin: "", error: JUNK };
  if (hostname.length > 253) {
    return { raw: text, host: "", origin: "", error: "That hostname is too long." };
  }

  const local = isLocalOrIp(hostname);
  if (!local) {
    const err = validateHostname(hostname);
    if (err) return { raw: text, host: "", origin: "", error: err };
  }

  const host = local ? hostname : applyFarmPrefix(hostname);
  if (!local) {
    const err = validateHostname(host);
    if (err) return { raw: text, host: "", origin: "", error: err };
  }

  let scheme: string;
  if (schemeIn === "http" || schemeIn === "https") {
    scheme = local ? schemeIn : "https";
  } else {
    scheme = local ? "http" : "https";
  }

  const hostport = formatHostPort(host, port, scheme);
  return { raw: text, host: hostport, origin: `${scheme}://${hostport}`, error: "" };
}

function parseInput(text: string): { scheme: string; hostname: string; port: number | null } {
  let candidate: string;
  let scheme = "";
  if (text.includes("://")) {
    const schemePart = text.split("://", 1)[0]?.toLowerCase() || "";
    if (schemePart !== "http" && schemePart !== "https") {
      throw new Error("Use http:// or https://, or enter a domain with no scheme.");
    }
    scheme = schemePart;
    candidate = text;
  } else {
    let body = text.replace(/^\/+/, "");
    if (isBareIPv6(body)) body = `[${body}]`;
    candidate = `http://${body}`;
  }
  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    throw new Error(JUNK);
  }
  if (url.username || url.password) throw new Error(JUNK);
  const hostname = url.hostname.replace(/^\[/, "").replace(/]$/, "");
  if (!hostname) throw new Error(JUNK);
  let port: number | null = null;
  if (url.port) {
    const n = Number(url.port);
    if (!Number.isInteger(n) || n < 1 || n > 65535) {
      throw new Error("That port number is not valid.");
    }
    port = n;
  }
  return { scheme, hostname, port };
}

function isBareIPv6(text: string): boolean {
  const head = text.split("/")[0] || "";
  if (head.startsWith("[")) return false;
  return isIPv6(head.split("%")[0] || "");
}

function isLocalOrIp(host: string): boolean {
  if (host === "localhost" || host.endsWith(".localhost")) return true;
  return isIPv4(host) || isIPv6(host);
}

function applyFarmPrefix(host: string): string {
  let labels = host.split(".").filter(Boolean);
  if (!labels.length) return host;
  if (labels[0] === "www" && labels.length > 1) {
    labels = labels.slice(1);
    host = labels.join(".");
  }
  if (labels[0] === "farm") return host;
  if (!host.includes(".")) return host;
  return `farm.${host}`;
}

function validateHostname(host: string): string {
  const labels = host.split(".");
  if (labels.some((label) => !label)) return "That domain has an empty label (check the dots).";
  if (labels.some((label) => !LABEL.test(label))) return JUNK;
  return "";
}

function formatHostPort(host: string, port: number | null, scheme: string): string {
  const display = isIPv6(host) ? `[${host}]` : host;
  const defaultPort = scheme === "https" ? 443 : 80;
  if (port && port !== defaultPort) return `${display}:${port}`;
  return display;
}

function isIPv4(host: string): boolean {
  const parts = host.split(".");
  if (parts.length !== 4) return false;
  return parts.every((p) => {
    if (!/^\d{1,3}$/.test(p)) return false;
    const n = Number(p);
    return n >= 0 && n <= 255 && String(n) === p;
  });
}

function isIPv6(host: string): boolean {
  if (!host.includes(":")) return false;
  // URL constructor already accepted it; a colon-separated host that is not a hostname label.
  if (/^[0-9a-f:.]+$/i.test(host) && /:/.test(host)) return true;
  return false;
}
