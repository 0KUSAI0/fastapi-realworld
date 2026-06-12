"""content governance workflow

Revision ID: d7f1a2b3c4e5
Revises: c2b7d4a1f3e2
Create Date: 2026-06-03 17:05:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import func

revision = "d7f1a2b3c4e5"
down_revision = "c2b7d4a1f3e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_audit_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("content_type", sa.Text, nullable=False),
        sa.Column(
            "article_id",
            sa.Integer,
            sa.ForeignKey("articles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "comment_id",
            sa.Integer,
            sa.ForeignKey("commentaries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("from_status", sa.Text, nullable=False, server_default=""),
        sa.Column("to_status", sa.Text, nullable=False, server_default=""),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "metadata",
            sa.JSON,
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    op.create_index(
        "content_audit_logs_content_idx",
        "content_audit_logs",
        ["content_type", "article_id", "comment_id"],
    )
    op.create_index(
        "content_audit_logs_created_at_idx",
        "content_audit_logs",
        ["created_at"],
    )

    op.create_table(
        "content_reports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("content_type", sa.Text, nullable=False),
        sa.Column(
            "reporter_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "article_id",
            sa.Integer,
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "comment_id",
            sa.Integer,
            sa.ForeignKey("commentaries.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("detail", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("resolution_note", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "resolved_by_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    op.create_index("content_reports_status_idx", "content_reports", ["status"])
    op.create_index(
        "content_reports_content_idx",
        "content_reports",
        ["content_type", "article_id", "comment_id"],
    )

    op.create_table(
        "user_notifications",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("notification_type", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("is_read", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("content_type", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "article_id",
            sa.Integer,
            sa.ForeignKey("articles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "comment_id",
            sa.Integer,
            sa.ForeignKey("commentaries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
        sa.Column("read_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "user_notifications_user_read_idx",
        "user_notifications",
        ["user_id", "is_read"],
    )


def downgrade() -> None:
    op.drop_index("user_notifications_user_read_idx", table_name="user_notifications")
    op.drop_table("user_notifications")
    op.drop_index("content_reports_content_idx", table_name="content_reports")
    op.drop_index("content_reports_status_idx", table_name="content_reports")
    op.drop_table("content_reports")
    op.drop_index("content_audit_logs_created_at_idx", table_name="content_audit_logs")
    op.drop_index("content_audit_logs_content_idx", table_name="content_audit_logs")
    op.drop_table("content_audit_logs")
