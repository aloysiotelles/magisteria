ALTER TABLE document_technical_summaries DROP COLUMN related_documents_json;
ALTER TABLE document_technical_summaries DROP COLUMN keywords_json;
ALTER TABLE document_technical_summaries DROP COLUMN doctrinal_claims_json;
ALTER TABLE document_technical_summaries DROP COLUMN subtopics_json;
ALTER TABLE document_technical_summaries DROP COLUMN document_date;
ALTER TABLE document_technical_summaries DROP COLUMN author_or_authority;
DELETE FROM schema_migrations WHERE version = '0003_document_summary_metadata';
