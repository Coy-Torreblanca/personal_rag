"""Add summary column to documents.

Adds the nullable ``summary`` TEXT column that stores the LLM-generated
dense summary (DeepSeek worker stage) on the ``documents`` table. The column
is nullable because documents are processed asynchronously after upload, and
existing rows have no summary until they are reprocessed.

Revision ID: a7c3e9d21b4f
Revises: 5b13f629fe23
Create Date: 2026-08-02 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c3e9d21b4f'
down_revision: Union[str, Sequence[str], None] = '5b13f629fe23'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the ``documents.summary`` column (nullable TEXT)."""
    # TEXT (not VARCHAR) matches the model definition — see
    # ``DocumentBase.summary`` in ``packages/database/src/database/models.py``
    # — and mirrors ``document_chunks.content``. Nullable so existing rows
    # and in-flight documents without a summary remain valid.
    op.add_column('documents', sa.Column('summary', sa.TEXT(), nullable=True))


def downgrade() -> None:
    """Drop the ``documents.summary`` column."""
    op.drop_column('documents', 'summary')
