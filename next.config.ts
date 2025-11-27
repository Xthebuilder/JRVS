import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Enable standalone output for Docker deployment
  // This creates a minimal production build that can run independently
  output: "standalone",
};

export default nextConfig;
