CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    cts_urn TEXT NOT NULL,
    edition_note TEXT NOT NULL,
    license_note TEXT NOT NULL,
    raw_sha256 TEXT NOT NULL,
    raw_bytes INTEGER NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS works (
    work_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    cts_urn TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id)
);

CREATE TABLE IF NOT EXISTS passages (
    passage_id BIGSERIAL PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES works(work_id),
    canonical_ref TEXT NOT NULL UNIQUE,
    book TEXT NOT NULL,
    chapter TEXT NOT NULL,
    paragraph_index INTEGER NOT NULL,
    greek_text TEXT NOT NULL,
    english_text TEXT,
    greek_word_count INTEGER NOT NULL,
    english_word_count INTEGER NOT NULL DEFAULT 0,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS passages_work_ref_idx
    ON passages(work_id, book, chapter, paragraph_index);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id BIGSERIAL PRIMARY KEY,
    run_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);
