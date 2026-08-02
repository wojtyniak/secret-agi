"""bench tables (belief_probes, chat_labels) and agent_metrics.provider_failure

Brings the migration chain up to date with the schema the bench actually uses.
The M2 tables were only ever created by `SQLModel.metadata.create_all`, so a
database built by `alembic upgrade head` was missing them entirely.

Revision ID: 9c1f4a7b2e10
Revises: 0643cad4739b
Create Date: 2026-08-01 23:55:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c1f4a7b2e10"
down_revision: str | Sequence[str] | None = "0643cad4739b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "belief_probes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("game_id", sa.String(), nullable=False),
        sa.Column("player_id", sa.String(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("beliefs", sqlite.JSON(), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_belief_probes_game_id"), "belief_probes", ["game_id"], unique=False
    )
    op.create_index(
        op.f("ix_belief_probes_player_id"), "belief_probes", ["player_id"], unique=False
    )
    op.create_index(
        op.f("ix_belief_probes_round_number"),
        "belief_probes",
        ["round_number"],
        unique=False,
    )

    op.create_table(
        "chat_labels",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("game_id", sa.String(), nullable=False),
        sa.Column("message_id", sa.String(), nullable=False),
        sa.Column("speaker_id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("necessary", sa.Boolean(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("commitment", sa.Text(), nullable=True),
        sa.Column("commitment_kept", sa.Boolean(), nullable=True),
        sa.Column("judge_model", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_chat_labels_game_id"), "chat_labels", ["game_id"], unique=False
    )
    op.create_index(
        op.f("ix_chat_labels_message_id"), "chat_labels", ["message_id"], unique=False
    )
    op.create_index(
        op.f("ix_chat_labels_speaker_id"), "chat_labels", ["speaker_id"], unique=False
    )
    op.create_index(op.f("ix_chat_labels_label"), "chat_labels", ["label"], unique=False)

    op.add_column(
        "agent_metrics",
        sa.Column(
            "provider_failure",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        op.f("ix_agent_metrics_provider_failure"),
        "agent_metrics",
        ["provider_failure"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_agent_metrics_provider_failure"), table_name="agent_metrics")
    op.drop_column("agent_metrics", "provider_failure")

    op.drop_index(op.f("ix_chat_labels_label"), table_name="chat_labels")
    op.drop_index(op.f("ix_chat_labels_speaker_id"), table_name="chat_labels")
    op.drop_index(op.f("ix_chat_labels_message_id"), table_name="chat_labels")
    op.drop_index(op.f("ix_chat_labels_game_id"), table_name="chat_labels")
    op.drop_table("chat_labels")

    op.drop_index(op.f("ix_belief_probes_round_number"), table_name="belief_probes")
    op.drop_index(op.f("ix_belief_probes_player_id"), table_name="belief_probes")
    op.drop_index(op.f("ix_belief_probes_game_id"), table_name="belief_probes")
    op.drop_table("belief_probes")
