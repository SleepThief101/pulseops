"""add event minor unit exponent and is_synthetic flag

Revision ID: 9c4a12e8f3b1
Revises: 849f79e737c6
Create Date: 2026-11-25 18:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9c4a12e8f3b1"
down_revision: Union[str, Sequence[str], None] = "849f79e737c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add non-destructive monetary precision & synthetic-data tracking columns and backfill safely."""
    op.add_column("events", sa.Column("minor_unit_exponent", sa.SmallInteger(), nullable=True))
    op.add_column(
        "events",
        sa.Column(
            "is_synthetic",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_events_org_currency_synthetic",
        "events",
        ["organization_id", "currency", "is_synthetic"],
        unique=False,
    )

    # Normalize existing currency casing/whitespace safely
    op.execute(
        sa.text(
            """
            UPDATE events
            SET currency = CASE
                WHEN TRIM(currency) = '' THEN NULL
                ELSE UPPER(TRIM(currency))
            END
            WHERE currency IS NOT NULL
            """
        )
    )

    # Backfill synthetic origin flag from source and payload metadata
    op.execute(
        sa.text(
            """
            UPDATE events
            SET is_synthetic = TRUE
            WHERE source = 'fake'
               OR COALESCE(payload->>'synthetic', '') = 'true'
               OR COALESCE(payload->>'billing_mode', '') = 'mock_fallback'
            """
        )
    )

    # Backfill ISO-4217 minor_unit_exponent on existing monetary rows
    op.execute(
        sa.text(
            """
            UPDATE events
            SET minor_unit_exponent = CASE
                WHEN currency IN ('BIF','CLP','DJF','GNF','ISK','JPY','KMF','KRW','PYG','RWF','UGX','UYI','VND','VUV','XAF','XOF','XPF') THEN 0
                WHEN currency IN ('BHD','IQD','JOD','KWD','LYD','OMR','TND') THEN 3
                WHEN currency IN ('CLF','UYW') THEN 4
                WHEN currency IS NOT NULL THEN 2
                ELSE NULL
            END
            WHERE amount_cents IS NOT NULL
              AND minor_unit_exponent IS NULL
            """
        )
    )


def downgrade() -> None:
    """Remove additive monetary precision & synthetic-data tracking columns."""
    op.drop_index("ix_events_org_currency_synthetic", table_name="events")
    op.drop_column("events", "is_synthetic")
    op.drop_column("events", "minor_unit_exponent")
