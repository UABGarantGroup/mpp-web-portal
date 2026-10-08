"""add calendar weekdays and working shifts tables

Revision ID: 2d870805f420
Revises: 1a0afd5acf88
Create Date: 2026-10-08 14:44:56.227627

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2d870805f420'
down_revision: Union[str, Sequence[str], None] = '1a0afd5acf88'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'calendar_weekdays',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('calendar_id', sa.Integer(), nullable=False),
        sa.Column('day_type', sa.Integer(), nullable=False),
        sa.Column('day_working', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['calendar_id'], ['calendars.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_calendar_weekdays_calendar_id'), 'calendar_weekdays', ['calendar_id'], unique=False)
    op.create_index(op.f('ix_calendar_weekdays_id'), 'calendar_weekdays', ['id'], unique=False)

    op.create_table(
        'calendar_working_shifts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('weekday_id', sa.Integer(), nullable=False),
        sa.Column('from_time', sa.String(length=8), nullable=False),
        sa.Column('to_time', sa.String(length=8), nullable=False),
        sa.ForeignKeyConstraint(['weekday_id'], ['calendar_weekdays.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_calendar_working_shifts_id'), 'calendar_working_shifts', ['id'], unique=False)
    op.create_index(op.f('ix_calendar_working_shifts_weekday_id'), 'calendar_working_shifts', ['weekday_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_calendar_working_shifts_weekday_id'), table_name='calendar_working_shifts')
    op.drop_index(op.f('ix_calendar_working_shifts_id'), table_name='calendar_working_shifts')
    op.drop_table('calendar_working_shifts')
    op.drop_index(op.f('ix_calendar_weekdays_id'), table_name='calendar_weekdays')
    op.drop_index(op.f('ix_calendar_weekdays_calendar_id'), table_name='calendar_weekdays')
    op.drop_table('calendar_weekdays')
