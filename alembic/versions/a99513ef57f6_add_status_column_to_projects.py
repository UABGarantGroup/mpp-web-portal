"""add status column to projects

Revision ID: a99513ef57f6
Revises: 4e17ab92bc31
Create Date: 2026-10-10 16:21:21.423635

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a99513ef57f6'
down_revision: Union[str, Sequence[str], None] = '4e17ab92bc31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('projects', sa.Column('status', sa.String(length=32), nullable=False, server_default='OPEN'))
    op.create_index(op.f('ix_projects_status'), 'projects', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_projects_status'), table_name='projects')
    op.drop_column('projects', 'status')
