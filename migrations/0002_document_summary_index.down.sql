DROP INDEX IF EXISTS idx_document_technical_summaries_authority;
DELETE FROM schema_migrations WHERE version = '0002_document_summary_index';
