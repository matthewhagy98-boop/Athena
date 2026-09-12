import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Every backend prefix the frontend calls. Production serves the SPA from FastAPI's
// StaticFiles mount, so these are same-origin there and the proxy is dev-only -- which
// is exactly why a missing entry is easy to ship: the build passes, tests pass (MSW
// intercepts), and only `npm run dev` 404s.
const apiPaths = ["/search", "/compare", "/saved-searches", "/topics", "/users", "/papers"];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: Object.fromEntries(apiPaths.map((p) => [p, "http://localhost:8000"])),
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    globals: true,
    exclude: ["e2e/**", "node_modules/**"],
  },
});
