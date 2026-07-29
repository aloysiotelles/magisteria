CREATE TABLE IF NOT EXISTS user_search_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    original_query TEXT,
    normalized_topic TEXT NOT NULL,
    display_title TEXT NOT NULL,
    topic_category TEXT NOT NULL,
    depth_level TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'pt-BR',
    created_at TEXT NOT NULL,
    last_searched_at TEXT NOT NULL,
    search_count INTEGER NOT NULL DEFAULT 1,
    deleted_at TEXT,
    UNIQUE(user_id, normalized_topic)
);

CREATE INDEX IF NOT EXISTS idx_user_search_history_user_id
    ON user_search_history(user_id);
CREATE INDEX IF NOT EXISTS idx_user_search_history_created_at
    ON user_search_history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_search_history_normalized_topic
    ON user_search_history(normalized_topic);
CREATE INDEX IF NOT EXISTS idx_user_search_history_user_topic
    ON user_search_history(user_id, normalized_topic);

CREATE TABLE IF NOT EXISTS semantic_cache_entries (
    cache_key TEXT PRIMARY KEY,
    topic_key TEXT NOT NULL,
    semantic_signature TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    chunks_json TEXT NOT NULL,
    document_ids_json TEXT NOT NULL DEFAULT '[]',
    references_json TEXT NOT NULL DEFAULT '[]',
    corpus_version TEXT NOT NULL,
    taxonomy_version TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0,
    last_hit_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_semantic_cache_topic
    ON semantic_cache_entries(topic_key, expires_at);
CREATE INDEX IF NOT EXISTS idx_semantic_cache_versions
    ON semantic_cache_entries(corpus_version, taxonomy_version, strategy_version);

CREATE TABLE IF NOT EXISTS document_technical_summaries (
    source TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    document_type TEXT NOT NULL,
    authority_level INTEGER NOT NULL,
    topics_json TEXT NOT NULL DEFAULT '[]',
    references_json TEXT NOT NULL DEFAULT '[]',
    relevant_excerpt TEXT NOT NULL DEFAULT '',
    locator TEXT NOT NULL DEFAULT '',
    corpus_version TEXT NOT NULL,
    use_count INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_document_technical_summaries_authority
    ON document_technical_summaries(authority_level, use_count DESC);
