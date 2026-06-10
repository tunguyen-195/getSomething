"""
Revision ID: d5e6f7a8b9c1
Revises: c4f1a2b3c9d0
Create Date: 2026-05-02 00:00:01.000000

"""
from alembic import op


revision = "d5e6f7a8b9c1"
down_revision = "c4f1a2b3c9d0"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE audio_files
        SET file_path = regexp_replace(file_path, '^storage/audio[/\\\\]+', '')
        WHERE file_path LIKE 'storage/audio/%'
           OR file_path LIKE 'storage/audio\\\\%'
        """
    )


def downgrade():
    pass
