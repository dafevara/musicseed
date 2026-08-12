import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  outputFileTracingRoot: __dirname,
  // Proxy /api to the MusicSeed API backend
  async rewrites() {
    const apiUrl = process.env.API_URL ?? "http://127.0.0.1:8788";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
