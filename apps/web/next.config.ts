import type { NextConfig } from "next";
import path from "node:path";

// Internal API URL used when Next.js server proxies requests.
// In Docker: http://api:8000 (service name from docker-compose)
// In local dev: http://localhost:8000
const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://api:8000";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  typedRoutes: false,
  output: "standalone",
  outputFileTracingRoot: path.join(import.meta.dirname, "../.."),
  experimental: {
    // Next's rewrite proxy otherwise truncates request bodies at its 10 MB default.
    // Keep a little multipart overhead above the configured 500 MB file limit.
    proxyClientMaxBodySize: "510mb",
  },
  async headers() {
    return [
      {
        source: "/_next/static/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=0, must-revalidate",
          },
        ],
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_INTERNAL_URL}/api/:path*`,
      },
      {
        source: "/documents/:path*",
        destination: `${API_INTERNAL_URL}/documents/:path*`,
      },
      {
        source: "/documents",
        destination: `${API_INTERNAL_URL}/documents`,
      },
    ];
  },
};

export default nextConfig;
