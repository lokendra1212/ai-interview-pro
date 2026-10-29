"""Persist the original uploaded resume file."""
from alembic import op
from sqlalchemy import Column, LargeBinary, String, inspect

revision = "002_store_resume_uploads"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("resumes")}
    if "file_data" not in columns:
        op.add_column("resumes", Column("file_data", LargeBinary(), nullable=True))
    if "content_type" not in columns:
        op.add_column("resumes", Column("content_type", String(120), nullable=True))


def downgrade():
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("resumes")}
    if "content_type" in columns:
        op.drop_column("resumes", "content_type")
    if "file_data" in columns:
        op.drop_column("resumes", "file_data")
