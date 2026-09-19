-- Keep legacy materials/favorites intact. Only the new empty-surname profiles
-- are used for future production and discovery.
CREATE TABLE IF NOT EXISTS app_seen_names (
    owner TEXT NOT NULL REFERENCES app_users(id),
    given_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (owner, given_name)
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM app_migrations WHERE id='shared-name-pools-v1') THEN
        IF NOT pg_try_advisory_xact_lock(2026091702) THEN
            RAISE EXCEPTION 'Stop the inventory producer before migrating shared pools';
        END IF;
        ALTER TABLE app_profiles DROP CONSTRAINT app_profiles_surname_check;
        ALTER TABLE app_profiles ADD CONSTRAINT app_profiles_surname_check
            CHECK (char_length(surname) BETWEEN 0 AND 2);
        UPDATE app_profiles SET enabled=false WHERE surname<>'';
        INSERT INTO app_profiles(surname,name_length) VALUES ('',1),('',2)
            ON CONFLICT(surname,name_length) DO NOTHING;
        INSERT INTO app_seen_names(owner,given_name,created_at)
            SELECT d.owner,m.given_name,min(d.created_at)
            FROM app_deliveries d JOIN app_materials m ON m.id=d.material_id
            GROUP BY d.owner,m.given_name
            ON CONFLICT DO NOTHING;
        INSERT INTO app_migrations(id,summary) VALUES
            ('shared-name-pools-v1','{"queues":[1,2],"legacy_favorites_preserved":true}'::jsonb);
    END IF;
END $$;
