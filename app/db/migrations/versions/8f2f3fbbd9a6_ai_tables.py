"""ai tables

Revision ID: 8f2f3fbbd9a6
Revises: fdf8821871d7
Create Date: 2026-05-29 14:40:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import func

revision = "8f2f3fbbd9a6"
down_revision = "fdf8821871d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "comment_moderation_logs",
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
        sa.Column(
            "comment_id",
            sa.Integer,
            sa.ForeignKey("commentaries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("allowed", sa.Boolean, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("suggested_revision", sa.Text, nullable=False, server_default=""),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("model_name", sa.Text, nullable=False),
        sa.Column("raw_response", sa.JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    op.create_table(
        "article_embeddings",
        sa.Column(
            "article_id",
            sa.Integer,
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("model_name", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("embedding", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    op.execute(
        """
        ALTER TABLE article_embeddings
        ALTER COLUMN embedding TYPE vector(384)
        USING embedding::vector
        """,
    )
    op.execute(
        """
        CREATE INDEX article_embeddings_embedding_hnsw_idx
        ON article_embeddings
        USING hnsw (embedding vector_cosine_ops)
        """
    )


def downgrade() -> None:
    op.drop_table("article_embeddings")
    op.drop_table("comment_moderation_logs")
