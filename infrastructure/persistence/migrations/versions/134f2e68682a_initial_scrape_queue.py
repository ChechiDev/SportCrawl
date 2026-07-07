"""initial_scrape_queue

Revision ID: 134f2e68682a
Revises:
Create Date: 2026-07-07 19:11:05.383298

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '134f2e68682a'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_scrapestatus = sa.Enum('PENDING', 'IN_PROGRESS', 'DONE', 'FAILED', name='scrapestatus')

_trigger_fn = """
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_trigger = """
CREATE TRIGGER trg_scrape_queue_updated_at
    BEFORE UPDATE ON scrape_queue
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
"""

_now = sa.text('now()')


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'scrape_queue',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('domain', sa.Text(), nullable=False),
        sa.Column('status', _scrapestatus, server_default='PENDING', nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=_now, nullable=False,
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=_now, nullable=False,
        ),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column(
            'retry_count', sa.Integer(), server_default=sa.text('0'), nullable=False
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('url', name='uq_scrape_queue_url'),
    )
    op.create_index(
        'ix_scrape_queue_domain_status',
        'scrape_queue',
        ['domain', 'status'],
        unique=False,
    )
    op.execute(_trigger_fn)
    op.execute(_trigger)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS trg_scrape_queue_updated_at ON scrape_queue")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column()")
    op.drop_index('ix_scrape_queue_domain_status', table_name='scrape_queue')
    op.drop_table('scrape_queue')
    _scrapestatus.drop(op.get_bind(), checkfirst=True)
