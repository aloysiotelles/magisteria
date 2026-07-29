DROP TABLE IF EXISTS document_technical_summaries;
DROP TABLE IF EXISTS semantic_cache_entries;
DROP TABLE IF EXISTS user_search_history;

-- SQLite cannot safely drop legacy columns on every supported runtime. The
-- diagnostic columns are intentionally retained during rollback; they contain
-- only aggregate technical counters and do not affect older application code.
DELETE FROM schema_migrations WHERE version = '0001_composite_queries';
