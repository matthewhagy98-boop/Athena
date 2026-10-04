"""Enforce that search_index_sync_state holds at most one row

`webapp/search_index.py` treats this table as a singleton -- `_get_or_create_sync_state`
reads it with `scalar_one_or_none()` -- but nothing enforced that. The table had only its
primary key, so select-then-insert raced:

    two processes start sync on a database with no watermark row
    both SELECT, both find nothing, both INSERT, both commit
    -> 2 rows, and every later call raises MultipleResultsFound

Reproduced before writing this migration: after two concurrent first-runs the next
`sync_search_index` raised MultipleResultsFound, which permanently breaks search indexing
until somebody deletes a row by hand. It needs a fresh database and two processes starting
together -- a first deploy, or a restored backup with the index rebuilt in parallel.

A unique index on the constant expression `(true)` is the standard way to say "at most one
row" in Postgres without adding a discriminator column nothing would read.

Deliberately NOT built CONCURRENTLY, unlike c41f8a20b7de and d8f3b61a04c7: those are on
`change_events`, a large table written continuously by the ingestion pipeline, where the
build lock would stall ingestion. This table holds one row.

The migration collapses any existing duplicates first, keeping the newest watermark --
newest rather than oldest because the watermark only moves forward, and re-examining
events a second time is harmless (`_reindex_paper` upserts) while skipping them is not.

Revision ID: e5a71c8d9f20
Revises: d8f3b61a04c7
"""

from alembic import op

revision = "e5a71c8d9f20"
down_revision = "d8f3b61a04c7"
branch_labels = None
depends_on = None

INDEX = "uq_search_index_sync_state_singleton"


def upgrade() -> None:
    # Collapse duplicates before the constraint can reject them. Keeps the latest
    # watermark; see the note above on why newest is the safe direction.
    op.execute(
        """
        DELETE FROM search_index_sync_state
        WHERE id NOT IN (
            SELECT id FROM search_index_sync_state
            ORDER BY last_synced_at DESC, id DESC
            LIMIT 1
        )
        """
    )
    op.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX} ON search_index_sync_state ((true))")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX}")
