import type { NextConfig } from "next";

const BACKEND_URL =
  process.env.API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  async rewrites() {
    return [
      {
        source: "/data/:path*",
        destination: `${BACKEND_URL}/data/:path*`,
      },
    ];
  },
};

export default nextConfig;
