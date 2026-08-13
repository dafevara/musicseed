import type { NextConfig } from "next";

const exporting = process.env.NEXT_OUTPUT === "export";

const nextConfig: NextConfig = {
  outputFileTracingRoot: __dirname,
  trailingSlash: true,
  ...(exporting ? { output: "export" as const } : {}),
};

if (!exporting) {
  nextConfig.rewrites = async () => {
    const apiUrl = process.env.API_URL ?? "http://127.0.0.1:8789";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/:path*`,
      },
    ];
  };
}

export default nextConfig;
