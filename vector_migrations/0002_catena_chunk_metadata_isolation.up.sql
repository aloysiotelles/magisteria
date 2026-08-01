CREATE TABLE IF NOT EXISTS catena_chunk_metadata (
    chunk_id TEXT PRIMARY KEY,
    collection TEXT NOT NULL DEFAULT '',
    work TEXT NOT NULL DEFAULT '',
    compiler TEXT NOT NULL DEFAULT '',
    gospel TEXT NOT NULL DEFAULT '',
    chapter INTEGER,
    verse_start INTEGER,
    verse_end INTEGER,
    pericope TEXT NOT NULL DEFAULT '',
    patristic_author TEXT NOT NULL DEFAULT '',
    patristic_authors_json TEXT NOT NULL DEFAULT '[]',
    source_work TEXT NOT NULL DEFAULT '',
    attributions_json TEXT NOT NULL DEFAULT '[]',
    language TEXT NOT NULL DEFAULT '',
    document_id TEXT NOT NULL DEFAULT '',
    previous_chunk_id TEXT,
    next_chunk_id TEXT,
    chunk_sequence INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_catena_chunk_metadata_collection
    ON catena_chunk_metadata(collection, gospel, chapter);
CREATE INDEX IF NOT EXISTS idx_catena_chunk_metadata_passage
    ON catena_chunk_metadata(gospel, chapter, verse_start, verse_end);
CREATE INDEX IF NOT EXISTS idx_catena_chunk_metadata_author
    ON catena_chunk_metadata(patristic_author);
CREATE INDEX IF NOT EXISTS idx_catena_chunk_metadata_document_sequence
    ON catena_chunk_metadata(document_id, chunk_sequence);
