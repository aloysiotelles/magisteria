DROP INDEX IF EXISTS idx_catena_chunk_metadata_document_sequence;
DROP INDEX IF EXISTS idx_catena_chunk_metadata_author;
DROP INDEX IF EXISTS idx_catena_chunk_metadata_passage;
DROP INDEX IF EXISTS idx_catena_chunk_metadata_collection;
DROP TABLE IF EXISTS catena_chunk_metadata;
DELETE FROM schema_migrations WHERE version = '0002_catena_chunk_metadata_isolation';
