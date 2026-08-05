import { defineConfig } from "@playwright/test";

// Override on machines whose interpreter differs (CI, Linux, non-Rosetta Macs):
//   ATHENA_UVICORN="python -m uvicorn" npm run e2e
const uvicorn = process.env.ATHENA_UVICORN ?? "arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/uvicorn";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  use: { baseURL: "http://localhost:8123" },
  webServer: {
    command: `cd ../.. && ${uvicorn} webapp.api:app --port 8123`,
    url: "http://localhost:8123/topics",
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
