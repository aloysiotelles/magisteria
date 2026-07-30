CREATE INDEX IF NOT EXISTS idx_document_technical_summaries_authority
    ON document_technical_summaries(authority_level, use_count DESC);
