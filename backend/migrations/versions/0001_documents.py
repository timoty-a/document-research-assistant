"""Create documents with atomic row-level storage and validation constraints."""

from alembic import op
import sqlalchemy as sa

revision = "0001_documents"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("original_byte_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("length(original_filename) > 0", name="ck_documents_filename_nonempty"),
        sa.CheckConstraint("lower(right(original_filename, 4)) = '.txt'", name="ck_documents_txt_extension"),
        sa.CheckConstraint("original_byte_size BETWEEN 1 AND 1048576", name="ck_documents_byte_size"),
        sa.CheckConstraint(
            "length(btrim(content, U&'\\0009\\000A\\000B\\000C\\000D"
            "\\001C\\001D\\001E\\001F\\0020\\0085\\00A0\\1680"
            "\\2000\\2001\\2002\\2003\\2004\\2005\\2006\\2007"
            "\\2008\\2009\\200A\\2028\\2029\\202F\\205F\\3000')) > 0",
            name="ck_documents_content_nonblank",
        ),
        sa.CheckConstraint(
            "octet_length(convert_to(content, 'UTF8')) = original_byte_size",
            name="ck_documents_utf8_byte_size",
        ),
    )


def downgrade() -> None:
    op.drop_table("documents")
