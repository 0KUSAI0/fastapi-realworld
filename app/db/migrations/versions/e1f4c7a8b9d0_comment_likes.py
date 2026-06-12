"""comment likes

Revision ID: e1f4c7a8b9d0
Revises: d7f1a2b3c4e5
Create Date: 2026-06-06 12:40:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import func

revision = "e1f4c7a8b9d0"
down_revision = "d7f1a2b3c4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "comment_likes",
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "comment_id",
            sa.Integer,
            sa.ForeignKey("commentaries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    op.create_primary_key(
        "pk_comment_likes",
        "comment_likes",
        ["user_id", "comment_id"],
    )
    op.create_index(
        "comment_likes_comment_id_idx",
        "comment_likes",
        ["comment_id"],
    )


def downgrade() -> None:
    op.drop_index("comment_likes_comment_id_idx", table_name="comment_likes")
    op.drop_table("comment_likes")
