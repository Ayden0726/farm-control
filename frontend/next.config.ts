import type { NextConfig } from "next";

const api = process.env.API_INTERNAL_URL || "http://127.0.0.1:8472";

const nextConfig: NextConfig = {
  output: "standalone",
  // Preview and local browsers hit 127.0.0.1; Next 16 otherwise 403s /_next chunks
  // so the login form never hydrates and pages stay on their SSR “Loading…” text.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${api}/api/:path*` },
      { source: "/health", destination: `${api}/health` },
    ];
  },
  async headers() {
    return [
      {
        source: "/sw.js",
        headers: [{ key: "Cache-Control", value: "no-store, max-age=0" }],
      },
    ];
  },
};

export default nextConfig;
