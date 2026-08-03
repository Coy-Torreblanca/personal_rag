import type { NextConfig } from "next";

// Next.js blocks cross-origin requests to dev resources (e.g. the HMR
// websocket) for safety. CORS_ALLOWED_ORIGINS holds full origins
// (e.g. "http://localhost:3000,https://app.example.com") for the API's
// CORS middleware; here we reduce each entry to its hostname because
// allowedDevOrigins matches against bare hostnames, not URLs.
const allowedDevOrigins = (process.env.CORS_ALLOWED_ORIGINS ?? "")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean)
  .map((origin) => {
    // Full origin ("http://localhost:3000") -> hostname ("localhost")
    if (origin.includes("://")) {
      try {
        return new URL(origin).hostname;
      } catch {
        return origin;
      }
    }
    // Already a bare hostname or wildcard pattern (e.g. "*.local-origin.dev")
    return origin;
  });

const nextConfig: NextConfig = {
  allowedDevOrigins,
};

export default nextConfig;
