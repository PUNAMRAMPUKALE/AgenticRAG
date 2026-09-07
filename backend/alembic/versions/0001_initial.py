"""Initial Postgres schema for chats, users, audit, and ingest runs."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("conversations"):
        return

    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("is_manager", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_table(
        "conversations",
        sa.Column("session_id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.ForeignKeyConstraint(["user_id"], ["user_profiles.id"], name="fk_conversations_user_profile", ondelete="CASCADE"),
    )
    op.create_index("ix_conversations_user_created", "conversations", ["user_id", "created_at"])
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("conversations.session_id"), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
    )
    op.create_index("ix_messages_session_created", "messages", ["session_id", "created_at"])
    op.create_table(
        "requests",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("user_query", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("idx_requests_user_created", "requests", ["user_id", "created_at"])
    op.create_table(
        "knowledge_ingest_runs",
        sa.Column("run_id", sa.String(length=36), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("knowledge_source", sa.String(length=16), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("index_version", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("files_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files_rechunked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files_reused", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files_deleted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunks_indexed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('running', 'succeeded', 'failed')", name="ck_ingest_runs_status"),
        sa.CheckConstraint("knowledge_source IN ('s3', 'local')", name="ck_ingest_runs_source"),
    )
    op.create_index("ix_ingest_runs_started", "knowledge_ingest_runs", ["started_at"])
    op.create_index("ix_ingest_runs_status_started", "knowledge_ingest_runs", ["status", "started_at"])


def downgrade() -> None:
    op.drop_table("knowledge_ingest_runs")
    op.drop_table("requests")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("user_profiles")
