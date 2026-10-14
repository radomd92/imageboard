"""Ranked discovery and durable sparse vector indexing.

Revision ID: 0008_discovery_vectors
Revises: 0007_larger_comments
"""

from alembic import op

revision = "0008_discovery_vectors"
down_revision = "0007_larger_comments"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("image_hits_rank_idx", "image", ["hits", "id"])
    op.create_index("image_favorite_image_idx", "image_favorite", ["image_id"])
    op.execute("""
        CREATE TABLE embedding_setting (
            id integer PRIMARY KEY CHECK (id = 1),
            version text NOT NULL,
            tag_weight real NOT NULL CHECK (tag_weight > 0),
            updated_at timestamptz NOT NULL DEFAULT NOW()
        );
        CREATE TABLE image_embedding (
            image_id integer PRIMARY KEY REFERENCES image(id) ON DELETE CASCADE,
            version text NOT NULL,
            source_hash varchar(64) NOT NULL,
            built_revision bigint NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT NOW()
        );
        CREATE TABLE image_embedding_term (
            image_id integer NOT NULL REFERENCES image_embedding(image_id) ON DELETE CASCADE,
            term varchar(160) NOT NULL,
            weight double precision NOT NULL CHECK (weight > 0 AND weight <= 1),
            PRIMARY KEY (image_id, term)
        );
        CREATE INDEX image_embedding_term_lookup_idx ON image_embedding_term (term, image_id) INCLUDE (weight);
        CREATE TABLE image_embedding_job (
            image_id integer PRIMARY KEY REFERENCES image(id) ON DELETE CASCADE,
            revision bigint NOT NULL DEFAULT 1,
            completed_revision bigint NOT NULL DEFAULT 0,
            status varchar(16) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'running', 'ready', 'empty', 'failed')),
            source_txid bigint NOT NULL DEFAULT txid_current(),
            priority integer NOT NULL DEFAULT 0,
            available_at timestamptz NOT NULL DEFAULT NOW(),
            lease_token uuid,
            lease_until timestamptz,
            attempts integer NOT NULL DEFAULT 0,
            last_error varchar(64),
            updated_at timestamptz NOT NULL DEFAULT NOW()
        );
        CREATE INDEX image_embedding_job_pending_idx ON image_embedding_job (priority DESC, available_at, image_id)
            WHERE status IN ('pending', 'failed', 'running');

        CREATE FUNCTION mark_image_embedding_dirty(target integer) RETURNS void LANGUAGE plpgsql AS $$
        BEGIN
            INSERT INTO image_embedding_job (image_id, priority)
            SELECT target, 1 WHERE EXISTS (SELECT 1 FROM image WHERE id = target)
            ON CONFLICT (image_id) DO UPDATE SET
                revision = image_embedding_job.revision + 1,
                status = 'pending', priority = 1, available_at = NOW(), lease_token = NULL, lease_until = NULL,
                attempts = 0, last_error = NULL, source_txid = txid_current(), updated_at = NOW()
            WHERE image_embedding_job.source_txid <> txid_current();
        END $$;
        CREATE FUNCTION message_embedding_dirty() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.image = OLD.image AND NEW.text IS NOT DISTINCT FROM OLD.text THEN
                RETURN NULL;
            END IF;
            IF TG_OP <> 'DELETE' THEN PERFORM mark_image_embedding_dirty(NEW.image); END IF;
            IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND OLD.image <> NEW.image) THEN
                PERFORM mark_image_embedding_dirty(OLD.image);
            END IF;
            RETURN NULL;
        END $$;
        CREATE TRIGGER message_embedding_changed AFTER INSERT OR DELETE OR UPDATE OF text, image ON message
            FOR EACH ROW EXECUTE FUNCTION message_embedding_dirty();
        CREATE FUNCTION tag_image_embedding_dirty() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.image = OLD.image AND NEW.tag = OLD.tag THEN RETURN NULL; END IF;
            IF TG_OP <> 'DELETE' THEN PERFORM mark_image_embedding_dirty(NEW.image); END IF;
            IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND OLD.image <> NEW.image) THEN
                PERFORM mark_image_embedding_dirty(OLD.image);
            END IF;
            RETURN NULL;
        END $$;
        CREATE TRIGGER tag_image_embedding_changed AFTER INSERT OR DELETE OR UPDATE ON tag_image
            FOR EACH ROW EXECUTE FUNCTION tag_image_embedding_dirty();
        CREATE FUNCTION tag_name_embedding_dirty() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE target integer;
        BEGIN
            FOR target IN SELECT image FROM tag_image WHERE tag = NEW.id LOOP
                PERFORM mark_image_embedding_dirty(target);
            END LOOP;
            RETURN NULL;
        END $$;
        CREATE TRIGGER tag_name_embedding_changed AFTER UPDATE OF name ON tag
            FOR EACH ROW WHEN (OLD.name IS DISTINCT FROM NEW.name) EXECUTE FUNCTION tag_name_embedding_dirty();

        INSERT INTO image_embedding_job (image_id)
        SELECT i.id FROM image i WHERE EXISTS (SELECT 1 FROM tag_image ti WHERE ti.image = i.id)
            OR EXISTS (SELECT 1 FROM message m WHERE m.image = i.id);
    """)


def downgrade():
    op.execute("""
        DROP TRIGGER tag_name_embedding_changed ON tag;
        DROP TRIGGER tag_image_embedding_changed ON tag_image;
        DROP TRIGGER message_embedding_changed ON message;
        DROP FUNCTION tag_name_embedding_dirty();
        DROP FUNCTION tag_image_embedding_dirty();
        DROP FUNCTION message_embedding_dirty();
        DROP FUNCTION mark_image_embedding_dirty(integer);
    """)
    op.drop_table("image_embedding_job")
    op.drop_table("image_embedding_term")
    op.drop_table("image_embedding")
    op.drop_table("embedding_setting")
    op.drop_index("image_favorite_image_idx", table_name="image_favorite")
    op.drop_index("image_hits_rank_idx", table_name="image")
