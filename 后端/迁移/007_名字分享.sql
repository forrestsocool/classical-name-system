-- Shared links identify one reviewed, delivered name without exposing the sender's surname.
-- A recipient may deliberately keep another source for a name already seen in the feed.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM app_migrations WHERE id='name-sharing-v1') THEN
        ALTER TABLE app_deliveries DROP CONSTRAINT app_deliveries_pkey;
        ALTER TABLE app_deliveries ADD CONSTRAINT app_deliveries_pkey PRIMARY KEY (owner, material_id);
        INSERT INTO app_migrations(id,summary) VALUES
            ('name-sharing-v1','{"links":"opaque","delivery_key":"owner_material"}'::jsonb);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS app_share_links (
    token TEXT PRIMARY KEY CHECK (char_length(token)=32),
    owner TEXT NOT NULL,
    material_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(owner, material_id),
    FOREIGN KEY(owner, material_id) REFERENCES app_deliveries(owner, material_id)
);
