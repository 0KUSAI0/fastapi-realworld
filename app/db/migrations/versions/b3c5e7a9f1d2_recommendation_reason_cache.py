"""recommendation reason cache

Revision ID: b3c5e7a9f1d2
Revises: e1f4c7a8b9d0
Create Date: 2026-06-11 10:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import func

revision = "b3c5e7a9f1d2"
down_revision = "e1f4c7a8b9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recommendation_reason_cache",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "source_article_id",
            sa.Integer,
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_article_id",
            sa.Integer,
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_name", sa.Text, nullable=False),
        sa.Column("relevance_score", sa.Float, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_recommendation_reason_cache",
        "recommendation_reason_cache",
        ["source_article_id", "target_article_id", "model_name"],
    )
    op.create_index(
        "recommendation_reason_cache_source_idx",
        "recommendation_reason_cache",
        ["source_article_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "recommendation_reason_cache_source_idx",
        table_name="recommendation_reason_cache",
    )
    op.drop_table("recommendation_reason_cache")
