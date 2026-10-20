"""Preserve TXT documents and add bounded PDF source/page provenance."""
from alembic import op
import sqlalchemy as sa

revision = '0003_pdf_documents'
down_revision = '0002_auth'
branch_labels = None
depends_on = None

# Frozen expression: never import mutable application models into a migration.
NONBLANK = "length(btrim(text, U&'\\0009\\000A\\000B\\000C\\000D\\001C\\001D\\001E\\001F\\0020\\0085\\00A0\\1680\\2000\\2001\\2002\\2003\\2004\\2005\\2006\\2007\\2008\\2009\\200A\\2028\\2029\\202F\\205F\\3000')) > 0"


def upgrade():
    op.add_column('documents', sa.Column('source_format', sa.Text(), nullable=False, server_default=sa.text("'txt'")))
    op.add_column('documents', sa.Column('source_pdf', sa.LargeBinary(), nullable=True))
    op.add_column('documents', sa.Column('page_count', sa.Integer(), nullable=True))
    op.add_column('documents', sa.Column('extraction_version', sa.Text(), nullable=True))
    op.drop_constraint('ck_documents_txt_extension', 'documents', type_='check')
    op.drop_constraint('ck_documents_utf8_byte_size', 'documents', type_='check')
    op.create_check_constraint('ck_documents_format_extension', 'documents', "(source_format = 'txt' AND lower(right(original_filename, 4)) = '.txt') OR (source_format = 'pdf' AND lower(right(original_filename, 4)) = '.pdf')")
    op.create_check_constraint('ck_documents_utf8_byte_size', 'documents', "source_format != 'txt' OR octet_length(convert_to(content, 'UTF8')) = original_byte_size")
    op.create_check_constraint('ck_documents_text_limit', 'documents', "octet_length(convert_to(content, 'UTF8')) <= 2097152")
    op.create_check_constraint('ck_documents_source', 'documents', "(source_format = 'txt' AND source_pdf IS NULL AND page_count IS NULL AND extraction_version IS NULL) OR (source_format = 'pdf' AND source_pdf IS NOT NULL AND octet_length(source_pdf) = original_byte_size AND page_count IS NOT NULL AND page_count BETWEEN 1 AND 100 AND extraction_version IS NOT NULL AND length(extraction_version) BETWEEN 1 AND 100)")
    op.create_table('document_pages',
        sa.Column('document_id', sa.Uuid(), nullable=False),
        sa.Column('page_number', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('has_text', sa.Boolean(), sa.Computed(NONBLANK, persisted=True), nullable=False),
        sa.PrimaryKeyConstraint('document_id', 'page_number'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name='fk_pages_document', ondelete='CASCADE'),
        sa.CheckConstraint('page_number BETWEEN 1 AND 100', name='ck_pages_number'),
        sa.CheckConstraint("octet_length(convert_to(text, 'UTF8')) <= 262144", name='ck_pages_text_limit'),
    )


def downgrade():
    raise RuntimeError('PDF downgrade refused: would discard source/provenance; use a reviewed forward fix or recovery procedure')
