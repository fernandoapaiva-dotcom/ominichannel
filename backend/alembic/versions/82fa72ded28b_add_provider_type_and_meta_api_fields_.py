"""add_provider_type_and_meta_api_fields_to_whatsapp_numbers

Revision ID: 82fa72ded28b
Revises: 
Create Date: 2026-08-12 15:52:33.340513

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '82fa72ded28b'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('whatsapp_numbers', sa.Column('provider_type', sa.String(length=20), server_default='evolution', nullable=False))
    op.alter_column('whatsapp_numbers', 'instancia_evolution_api', existing_type=sa.String(length=100), nullable=True)
    op.add_column('whatsapp_numbers', sa.Column('meta_phone_number_id', sa.String(length=100), nullable=True))
    op.add_column('whatsapp_numbers', sa.Column('meta_waba_id', sa.String(length=100), nullable=True))
    op.add_column('whatsapp_numbers', sa.Column('meta_access_token_encrypted', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('whatsapp_numbers', 'meta_access_token_encrypted')
    op.drop_column('whatsapp_numbers', 'meta_waba_id')
    op.drop_column('whatsapp_numbers', 'meta_phone_number_id')
    op.alter_column('whatsapp_numbers', 'instancia_evolution_api', existing_type=sa.String(length=100), nullable=False)
    op.drop_column('whatsapp_numbers', 'provider_type')
