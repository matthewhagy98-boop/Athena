# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.

## Dashboard

`/` (and the sidebar's first entry) opens the Trending Dashboard. It is backed by a
backend feature flag, `DASHBOARD_ENABLED` (`Settings.dashboard_enabled` in
`evidence_engine/config.py`, default `false` — see `docs/dashboard-metrics.md` for the
full operator picture, including a note that this flag is not yet wired to any
frontend or backend gating).

**The "Most active topics" widget shows an empty ranking until the daily job has run at
least once.** This is expected, not a bug: the dashboard reads whatever the last run of
`scripts/refresh_dashboard_activity.py` published, and a freshly migrated database has
no such run yet. If the widget looks empty:

- For local development, run `scripts/seed_demo_data.py --run-dashboard-job` from the
  repo root — it seeds demo data and publishes a ranking in one command.
- Otherwise, run `python -m scripts.refresh_dashboard_activity` and check
  `dashboard_job_state.status`: `idle` with `topics_processed = 0` means the job ran but
  no topic met the activity threshold this week (a quiet week, not a failure); `failed`
  means the run errored and `last_error` has the reason. See `docs/dashboard-metrics.md`
  for the full explanation.
