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

CREATE TABLE IF NOT EXISTS ai_translation_runs (
    translation_run_id BIGSERIAL PRIMARY KEY,
    passage_id BIGINT NOT NULL REFERENCES passages(passage_id),
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    english_translation TEXT,
    notes TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    UNIQUE (passage_id, model, prompt_version)
);

CREATE TABLE IF NOT EXISTS comic_candidates (
    comic_candidate_id BIGSERIAL PRIMARY KEY,
    passage_id BIGINT NOT NULL REFERENCES passages(passage_id),
    candidate_score NUMERIC NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate',
    scoring_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (passage_id, scoring_version)
);

CREATE TABLE IF NOT EXISTS comic_plans (
    comic_plan_id BIGSERIAL PRIMARY KEY,
    passage_id BIGINT NOT NULL REFERENCES passages(passage_id),
    translation_run_id BIGINT REFERENCES ai_translation_runs(translation_run_id),
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    plan_json JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS comic_panels (
    comic_panel_id BIGSERIAL PRIMARY KEY,
    comic_plan_id BIGINT NOT NULL REFERENCES comic_plans(comic_plan_id),
    panel_number INTEGER NOT NULL,
    panel_title TEXT NOT NULL,
    panel_prompt TEXT NOT NULL,
    caption TEXT NOT NULL DEFAULT '',
    negative_prompt TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (comic_plan_id, panel_number)
);

CREATE TABLE IF NOT EXISTS comic_image_assets (
    comic_image_asset_id BIGSERIAL PRIMARY KEY,
    comic_panel_id BIGINT NOT NULL REFERENCES comic_panels(comic_panel_id),
    model TEXT NOT NULL,
    prompt_sha256 TEXT NOT NULL,
    local_path TEXT NOT NULL,
    s3_uri TEXT,
    public_path TEXT,
    sha256 TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    status TEXT NOT NULL DEFAULT 'generated',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
