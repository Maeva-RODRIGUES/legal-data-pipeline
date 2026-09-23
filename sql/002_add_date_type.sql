-- Date type filtered by collection (update | creation).
-- NULL for earlier runs, which relied on the API default value.
ALTER TABLE bronze.collection_runs
    ADD COLUMN IF NOT EXISTS date_type TEXT;
