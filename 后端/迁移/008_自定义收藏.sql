-- Private custom materials reuse delivery/favorite/detail contracts, never feed inventory.
ALTER TABLE app_materials ADD COLUMN IF NOT EXISTS custom_owner TEXT REFERENCES app_users(id);
ALTER TABLE app_materials ALTER COLUMN profile_id DROP NOT NULL;
ALTER TABLE app_materials ALTER COLUMN passage_id DROP NOT NULL;
DO $$ BEGIN
IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='app_materials_origin_check' AND conrelid='app_materials'::regclass) THEN
ALTER TABLE app_materials ADD CONSTRAINT app_materials_origin_check CHECK (
    (custom_owner IS NULL AND profile_id IS NOT NULL AND passage_id IS NOT NULL)
    OR (custom_owner IS NOT NULL AND profile_id IS NULL AND passage_id IS NULL AND book='用户自定义')
);
END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS app_materials_custom_name ON app_materials(custom_owner,given_name)
    WHERE custom_owner IS NOT NULL;
