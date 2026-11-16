import type { NextConfig } from "next";

// Built as a static site (frontend/out) that server.py serves on :8000.
// During `npm run dev`, the browser talks to the API at NEXT_PUBLIC_API_URL.
const nextConfig: NextConfig = {
  output: "export",
  reactCompiler: true,
  images: { unoptimized: true },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
