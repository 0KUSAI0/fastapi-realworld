"""content visibility status

Revision ID: c2b7d4a1f3e2
Revises: 9a41d8ce7b31
Create Date: 2026-06-03 14:55:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import func

revision = "c2b7d4a1f3e2"
down_revision = "9a41d8ce7b31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "articles",
        sa.Column("content_status", sa.Text, nullable=False, server_default="visible"),
    )
    op.add_column(
        "commentaries",
        sa.Column("content_status", sa.Text, nullable=False, server_default="visible"),
    )
    op.create_index("articles_content_status_idx", "articles", ["content_status"])
    op.create_index(
        "commentaries_content_status_idx",
        "commentaries",
        ["content_status"],
    )

    op.create_table(
        "article_moderation_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "article_id",
            sa.Integer,
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("allowed", sa.Boolean, nullable=False),
        sa.Column("content_score", sa.Integer, nullable=False),
        sa.Column("risk_labels", sa.JSON, nullable=False),
        sa.Column("summary", sa.Text, nullable=False, server_default=""),
        sa.Column("suggestions", sa.JSON, nullable=False),
        sa.Column("model_name", sa.Text, nullable=False),
        sa.Column("raw_response", sa.JSON, nullable=False),
        sa.Column("review_status", sa.Text, nullable=False, server_default="approved"),
        sa.Column("review_note", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    op.create_index(
        "article_moderation_logs_review_status_idx",
        "article_moderation_logs",
        ["review_status"],
    )
    op.create_index(
        "article_moderation_logs_article_id_idx",
        "article_moderation_logs",
        ["article_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "article_moderation_logs_article_id_idx",
        table_name="article_moderation_logs",
    )
    op.drop_index(
        "article_moderation_logs_review_status_idx",
        table_name="article_moderation_logs",
    )
    op.drop_table("article_moderation_logs")
    op.drop_index("commentaries_content_status_idx", table_name="commentaries")
    op.drop_index("articles_content_status_idx", table_name="articles")
    op.drop_column("commentaries", "content_status")
    op.drop_column("articles", "content_status")
