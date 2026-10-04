-- Preserve material IDs and their delivery/favorite foreign keys.
ALTER TABLE app_attempts ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT 'epoch';
ALTER TABLE passages ADD COLUMN IF NOT EXISTS active_for_recall BOOLEAN NOT NULL DEFAULT true;
UPDATE passages p SET active_for_recall=false FROM sources s
    WHERE p.source_id=s.id AND s.path ~ '\.archive-[0-9]+$' AND p.active_for_recall;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='app_materials_profile_name_book_key'
                   AND conrelid='app_materials'::regclass) THEN
        ALTER TABLE app_materials ADD CONSTRAINT app_materials_profile_name_book_key
            UNIQUE(profile_id,given_name,book);
    END IF;
    ALTER TABLE app_materials DROP CONSTRAINT IF EXISTS app_materials_profile_id_given_name_key;
END $$;

CREATE INDEX IF NOT EXISTS app_attempts_retry ON app_attempts(profile_id,book,last_attempt_at);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM app_migrations WHERE id='recall-recovery-v1') THEN
        UPDATE app_source_progress SET retry_at=now();
        INSERT INTO app_migrations(id,summary) VALUES
            ('recall-recovery-v1','{"retry_hours":1,"multi_source_materials":true}'::jsonb);
    END IF;
END $$;
