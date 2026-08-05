import { execFileSync } from "node:child_process";

// The demo rows the smoke test asserts on are seeded here rather than assumed.
// This matters because the backend suite's `reset_leaked_state` fixture
// truncates `paper_search_index`: after any pytest run the demo topic still
// exists but is unsearchable, which would fail the smoke test for a reason that
// has nothing to do with the frontend. Seeding on every run rebuilds the index.
//
// Override the interpreter on machines whose setup differs (CI, Linux):
//   ATHENA_PYTHON="python" npm run e2e
const DEFAULT_PYTHON = "arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/python";

export default function globalSetup(): void {
  const [bin, ...prefixArgs] = (process.env.ATHENA_PYTHON ?? DEFAULT_PYTHON).split(/\s+/).filter(Boolean);
  execFileSync(bin, [...prefixArgs, "-m", "scripts.seed_demo_data"], {
    cwd: "../..",
    stdio: "inherit",
  });
}
