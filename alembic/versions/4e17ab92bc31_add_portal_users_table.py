"""add portal_users table

Revision ID: 4e17ab92bc31
Revises: 3b61355fb11d
Create Date: 2026-10-09 15:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4e17ab92bc31'
down_revision = '3b61355fb11d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'portal_users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('entra_oid', sa.String(length=64), nullable=True),
        sa.Column('role', sa.String(length=50), nullable=False, server_default='PM'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('source', sa.String(length=50), nullable=False, server_default='MANUAL'),
        sa.Column('group_name', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_portal_users_id'), 'portal_users', ['id'], unique=False)
    op.create_index(op.f('ix_portal_users_email'), 'portal_users', ['email'], unique=True)
    op.create_index(op.f('ix_portal_users_entra_oid'), 'portal_users', ['entra_oid'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_portal_users_entra_oid'), table_name='portal_users')
    op.drop_index(op.f('ix_portal_users_email'), table_name='portal_users')
    op.drop_index(op.f('ix_portal_users_id'), table_name='portal_users')
    op.drop_table('portal_users')
