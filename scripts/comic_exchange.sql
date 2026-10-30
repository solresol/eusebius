-- Applied explicitly by server-side comic_exchange sync, never by a cloud worker.
CREATE TABLE IF NOT EXISTS comic_exchange_receipts (
    result_id TEXT PRIMARY KEY CHECK (result_id ~ '^[0-9a-f]{64}$'),
    comic_panel_id BIGINT NOT NULL REFERENCES comic_panels(comic_panel_id),
    claim_token TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    source_commit TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('accepted', 'rejected')),
    reason TEXT NOT NULL,
    comic_image_asset_id BIGINT REFERENCES comic_image_assets(comic_image_asset_id),
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS comic_exchange_one_accept_per_panel
    ON comic_exchange_receipts(comic_panel_id) WHERE status = 'accepted';

CREATE TABLE IF NOT EXISTS comic_exchange_files (
    result_id TEXT NOT NULL REFERENCES comic_exchange_receipts(result_id),
    path TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('original', 'web', 'source', 'prompt', 'review', 'component')),
    s3_key TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_count BIGINT NOT NULL CHECK (byte_count > 0),
    PRIMARY KEY (result_id, path)
);
