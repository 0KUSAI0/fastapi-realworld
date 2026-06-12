"""moderation review status

Revision ID: 9a41d8ce7b31
Revises: 8f2f3fbbd9a6
Create Date: 2026-06-03 10:20:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "9a41d8ce7b31"
down_revision = "8f2f3fbbd9a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "comment_moderation_logs",
        sa.Column("review_status", sa.Text, nullable=False, server_default="pending"),
    )
    op.add_column(
        "comment_moderation_logs",
        sa.Column("review_note", sa.Text, nullable=False, server_default=""),
    )
    op.create_index(
        "comment_moderation_logs_review_status_idx",
        "comment_moderation_logs",
        ["review_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "comment_moderation_logs_review_status_idx",
        table_name="comment_moderation_logs",
    )
    op.drop_column("comment_moderation_logs", "review_note")
    op.drop_column("comment_moderation_logs", "review_status")
