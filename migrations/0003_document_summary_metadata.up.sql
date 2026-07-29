ALTER TABLE document_technical_summaries
    ADD COLUMN author_or_authority TEXT NOT NULL DEFAULT '';
ALTER TABLE document_technical_summaries
    ADD COLUMN document_date TEXT NOT NULL DEFAULT '';
ALTER TABLE document_technical_summaries
    ADD COLUMN subtopics_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE document_technical_summaries
    ADD COLUMN doctrinal_claims_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE document_technical_summaries
    ADD COLUMN keywords_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE document_technical_summaries
    ADD COLUMN related_documents_json TEXT NOT NULL DEFAULT '[]';
