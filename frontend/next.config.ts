import type { NextConfig } from "next";

const api = process.env.API_INTERNAL_URL || "http://127.0.0.1:8472";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [{ source: "/health", destination: `${api}/health` }];
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
