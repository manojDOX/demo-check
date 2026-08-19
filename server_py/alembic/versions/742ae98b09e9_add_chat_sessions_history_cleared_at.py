"""add chat_sessions.history_cleared_at

Revision ID: 742ae98b09e9
Revises: 336663095113
Create Date: 2026-08-19 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '742ae98b09e9'
down_revision: Union[str, None] = '336663095113'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chat_sessions', sa.Column('history_cleared_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('chat_sessions', 'history_cleared_at')
