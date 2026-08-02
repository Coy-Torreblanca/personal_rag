// ---------------------------------------------------------------------------
// Vitest configuration for the web app.
//
// - Resolves the `@/*` path alias exactly like `tsconfig.json` so tests can
//   import modules with the same specifiers as the app code.
// - Default environment is `node` (fast, sufficient for pure logic tests in
//   `src/lib/**`). Component tests opt into `jsdom` with a
//   `// @vitest-environment jsdom` docblock at the top of the test file.
// ---------------------------------------------------------------------------

import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
