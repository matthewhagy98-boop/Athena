"""change_events detected_at index, built concurrently

Split out of 07353c5bf8e0 deliberately. This index is on `change_events`, an
existing table owned by evidence_engine and written continuously by the ingestion
pipeline -- not one of the dashboard's own new tables. A plain CREATE INDEX takes a
lock that blocks writes to it for the whole build, which on a populated corpus
stalls ingestion for as long as the build takes.

CONCURRENTLY cannot run inside a transaction, hence the autocommit block. The
trade-off is that a failed concurrent build leaves an INVALID index behind, which
has to be dropped by hand before retrying -- acceptable, and the standard cost of
adding an index to a live table.

IF NOT EXISTS so this is a no-op on any database that already took the index from
the earlier version of 07353c5bf8e0.

Revision ID: c41f8a20b7de
Revises: 07353c5bf8e0
"""

from alembic import op

revision = "c41f8a20b7de"
down_revision = "07353c5bf8e0"
branch_labels = None
depends_on = None

INDEX = "ix_change_events_detected_at"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} ON change_events (detected_at)")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")
