"""change_events (topic_id, detected_at) composite index, built concurrently

`_first_event_at` is the one query in the dashboard job that cannot be bounded by a
window -- "the topic's earliest event ever" means reading history -- so it had no index
to ride and seq-scanned all of `change_events` on every daily run.

Scoping it to the eligible topics was not enough on its own. Measured on 200k events
across 500 topics, asking for 8 topics:

    no filter                  Parallel Seq Scan   cost 5419
    topic filter, no index     Parallel Seq Scan   cost 6017   (slightly worse)
    topic filter + this index  index scan          cost  144

The 144 figure came from a planner that chose an Index Only Scan on that particular
corpus. Review re-measured on a rebuilt 200k/500 corpus and got a Bitmap Heap Scan at
2139 -- so the win is real but roughly 2.5x, not 40x. Both measurements agree on the
thing that matters: the filter alone makes it slightly worse, and the index is what turns
a full scan into an index scan. Treat the exact number as corpus- and planner-dependent.

`change_events` previously had only its primary key and `ix_change_events_detected_at`,
neither of which can serve a per-topic aggregate. This index also covers
`dashboard/personal.py`, which filters `topic_id IN (...) AND detected_at > window_start`
and had no `topic_id` index to work from -- the same measurement puts that query at
cost 37 on an index-only scan.

Built CONCURRENTLY for the same reason as c41f8a20b7de: `change_events` is an existing
engine-owned table written continuously by the ingestion pipeline, and a plain
CREATE INDEX holds a lock that blocks writes for the whole build. CONCURRENTLY cannot
run inside a transaction, hence the autocommit block; the trade-off is that a failed
build leaves an INVALID index to drop by hand before retrying.

The leading `detected_at` index is deliberately kept: queries that filter on
`detected_at` alone -- `_counts_in_window`, `read_change_feed`, `sync_search_index` --
cannot use a composite whose leading column is `topic_id`.

Revision ID: d8f3b61a04c7
Revises: c41f8a20b7de
"""

from alembic import op

revision = "d8f3b61a04c7"
down_revision = "c41f8a20b7de"
branch_labels = None
depends_on = None

INDEX = "ix_change_events_topic_id_detected_at"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} "
            "ON change_events (topic_id, detected_at)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")
