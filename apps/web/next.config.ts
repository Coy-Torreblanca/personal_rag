import type { NextConfig } from "next";

// Next.js blocks cross-origin requests to dev resources (e.g. the HMR
// websocket) for safety. Allow the comma-separated hostnames from
// CORS_ALLOWED_ORIGINS (injected via docker-compose) so the dev site can be
// browsed from other machines on the Tailscale tailnet.
const allowedDevOrigins = (process.env.CORS_ALLOWED_ORIGINS ?? "")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);

const nextConfig: NextConfig = {
  allowedDevOrigins,
};

export default nextConfig;
