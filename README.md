## Running the daily cycle

Requires `docker compose up -d postgres`, a `.env` file (copy from `.env.example`), and migrations applied via `uv run alembic upgrade head`.

Run once manually:

    uv run python -m scripts.run_daily_cycle

In production, schedule this as a daily cron job / systemd timer / cloud-scheduler-triggered job — no task queue is required for v1 (see spec section 2).
