"""add kpi_cache

Revision ID: a4f61d92c7b8
Revises: c3053425a1a0
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a4f61d92c7b8'
down_revision: Union[str, None] = 'c3053425a1a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'kpi_cache',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False),
        sa.Column('endpoint', sa.String(), nullable=False),
        sa.Column('params_hash', sa.String(), nullable=False),
        sa.Column('params', sa.JSON(), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('computed_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('client_id', 'endpoint', 'params_hash', name='uq_kpi_cache_key'),
    )


def downgrade() -> None:
    op.drop_table('kpi_cache')
