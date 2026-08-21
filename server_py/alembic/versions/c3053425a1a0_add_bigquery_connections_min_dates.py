"""add bigquery_connections min_session_date/min_customer_created_date

Revision ID: c3053425a1a0
Revises: 742ae98b09e9
Create Date: 2026-08-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3053425a1a0'
down_revision: Union[str, None] = '742ae98b09e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('bigquery_connections', sa.Column('min_session_date', sa.DateTime(), nullable=True))
    op.add_column('bigquery_connections', sa.Column('min_customer_created_date', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('bigquery_connections', 'min_customer_created_date')
    op.drop_column('bigquery_connections', 'min_session_date')
