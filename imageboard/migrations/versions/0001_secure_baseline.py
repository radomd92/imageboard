"""Secure baseline schema.

Revision ID: 0001_secure_baseline
"""

import sqlalchemy as sa
from alembic import op

revision = '0001_secure_baseline'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'image' in inspector.get_table_names():
        _upgrade_legacy_schema(bind, inspector)
        return

    op.create_table(
        'user',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('password', sa.String(512), nullable=False),
        sa.Column('registered', sa.DateTime(timezone=True), nullable=False),
        sa.Column('karma', sa.Integer(), server_default='0', nullable=False),
        sa.Column('privileges', sa.String(100), server_default='user', nullable=False),
        sa.Column('banned', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.UniqueConstraint('name'),
    )
    op.create_index('ix_user_name', 'user', ['name'], unique=True)
    op.create_table(
        'image',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('image_path', sa.Text(), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('created_date', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('file_size', sa.BigInteger()),
        sa.Column('hits', sa.Integer(), server_default='0', nullable=False),
        sa.Column('uploader', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL')),
        sa.UniqueConstraint('image_path'),
    )
    op.create_table(
        'tag',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.UniqueConstraint('name'),
    )
    op.create_index('ix_tag_name', 'tag', ['name'], unique=True)
    op.create_table(
        'tag_image',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('image', sa.Integer(), sa.ForeignKey('image.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tag', sa.Integer(), sa.ForeignKey('tag.id', ondelete='CASCADE'), nullable=False),
        sa.UniqueConstraint('tag', 'image', name='unique_tag_image'),
    )
    op.create_index('ix_tag_image_image', 'tag_image', ['image'])
    op.create_index('ix_tag_image_tag', 'tag_image', ['tag'])
    op.create_table(
        'ratings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('image', sa.Integer(), sa.ForeignKey('image.id', ondelete='CASCADE'), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('date', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('rating >= 1 AND rating <= 5', name='rating_between_1_and_5'),
    )
    op.create_table(
        'image_hits',
        sa.Column('hit_id', sa.Uuid(), primary_key=True),
        sa.Column('image_id', sa.Integer(), sa.ForeignKey('image.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL')),
        sa.Column('hit_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('type', sa.String(16), nullable=False),
        sa.CheckConstraint("type IN ('image', 'thumbnail')", name='valid_hit_type'),
    )
    op.create_index('image_hits_image_date_idx', 'image_hits', ['image_id', 'hit_date'])
    op.create_table(
        'message',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('from_user', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL')),
        sa.Column('image', sa.Integer(), sa.ForeignKey('image.id', ondelete='CASCADE'), nullable=False),
        sa.Column('text', sa.String(500), nullable=False),
        sa.Column('reply_to', sa.Integer(), sa.ForeignKey('message.id', ondelete='CASCADE')),
        sa.Column('message_date', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('message_image_date_idx', 'message', ['image', 'message_date'])
    op.create_table(
        'audit_event',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL')),
        sa.Column('action', sa.String(64), nullable=False),
        sa.Column('object_type', sa.String(64), nullable=False),
        sa.Column('object_id', sa.String(200), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('audit_event_date_idx', 'audit_event', ['created_at'])


def _upgrade_legacy_schema(bind, inspector):
    """Preserve legacy metadata while invalidating all pre-authentication accounts."""
    if bind.dialect.name != 'postgresql':
        raise RuntimeError('Legacy in-place upgrades are supported only for PostgreSQL.')

    # The old application never authenticated these records. Rename and disable
    # them so unknown password formats cannot accidentally become valid accounts.
    op.execute(sa.text('''
        UPDATE "user"
        SET name = 'legacy-user-' || id,
            password = '!disabled-reset-required!',
            registered = COALESCE(registered, CURRENT_TIMESTAMP),
            karma = COALESCE(karma, 0),
            privileges = 'user',
            banned = TRUE
    '''))
    op.alter_column('user', 'name', existing_type=sa.String(100), nullable=False)
    op.alter_column('user', 'password', existing_type=sa.String(256), type_=sa.String(512), nullable=False)
    op.alter_column('user', 'registered', existing_type=sa.DateTime(timezone=True), nullable=False)
    op.alter_column('user', 'karma', existing_type=sa.Integer(), nullable=False, server_default='0')
    op.alter_column('user', 'privileges', existing_type=sa.String(100), nullable=False, server_default='user')
    op.alter_column('user', 'banned', existing_type=sa.Boolean(), nullable=False, server_default=sa.true())
    _create_index_unless_present(inspector, 'user', 'ix_user_name', ['name'], unique=True)

    op.execute(sa.text("UPDATE image SET image_path = 'legacy-missing-' || id WHERE image_path IS NULL"))
    op.execute(sa.text('UPDATE image SET hits = COALESCE(hits, 0)'))
    op.alter_column('image', 'image_path', existing_type=sa.Text(), nullable=False)
    op.alter_column('image', 'hits', existing_type=sa.Integer(), nullable=False, server_default='0')

    op.execute(sa.text("UPDATE tag SET name = 'legacy-tag-' || id WHERE name IS NULL OR btrim(name) = ''"))
    op.alter_column('tag', 'name', existing_type=sa.String(100), nullable=False)
    _create_index_unless_present(inspector, 'tag', 'ix_tag_name', ['name'], unique=True)

    op.execute(sa.text('''
        DELETE FROM tag_image
        WHERE image IS NULL OR tag IS NULL
           OR NOT EXISTS (SELECT 1 FROM image WHERE image.id = tag_image.image)
           OR NOT EXISTS (SELECT 1 FROM tag WHERE tag.id = tag_image.tag)
    '''))
    op.alter_column('tag_image', 'image', existing_type=sa.Integer(), nullable=False)
    op.alter_column('tag_image', 'tag', existing_type=sa.Integer(), nullable=False)
    _create_index_unless_present(inspector, 'tag_image', 'ix_tag_image_image', ['image'])
    _create_index_unless_present(inspector, 'tag_image', 'ix_tag_image_tag', ['tag'])

    op.execute(sa.text('''
        DELETE FROM ratings
        WHERE "user" IS NULL OR image IS NULL OR rating NOT BETWEEN 1 AND 5
           OR NOT EXISTS (SELECT 1 FROM "user" WHERE "user".id = ratings."user")
           OR NOT EXISTS (SELECT 1 FROM image WHERE image.id = ratings.image)
    '''))
    op.execute(sa.text('UPDATE ratings SET date = COALESCE(date, CURRENT_TIMESTAMP)'))
    op.alter_column('ratings', 'user', existing_type=sa.Integer(), nullable=False)
    op.alter_column('ratings', 'image', existing_type=sa.Integer(), nullable=False)
    op.alter_column('ratings', 'rating', existing_type=sa.Integer(), nullable=False)
    op.alter_column('ratings', 'date', existing_type=sa.DateTime(timezone=True), nullable=False)
    op.create_check_constraint('rating_between_1_and_5', 'ratings', 'rating >= 1 AND rating <= 5')

    op.execute(sa.text('''
        DELETE FROM image_hits
        WHERE image_id IS NULL OR NOT EXISTS (SELECT 1 FROM image WHERE image.id = image_hits.image_id)
    '''))
    op.execute(sa.text('''
        UPDATE image_hits SET type = 'image'
        WHERE type NOT IN ('image', 'thumbnail') OR type IS NULL
    '''))
    op.execute(sa.text('UPDATE image_hits SET hit_date = COALESCE(hit_date, CURRENT_TIMESTAMP)'))
    op.alter_column('image_hits', 'image_id', existing_type=sa.Integer(), nullable=False)
    op.alter_column('image_hits', 'hit_date', existing_type=sa.DateTime(timezone=True), nullable=False)
    op.alter_column('image_hits', 'type', existing_type=sa.String(16), nullable=False)
    op.create_check_constraint('valid_hit_type', 'image_hits', "type IN ('image', 'thumbnail')")
    op.create_foreign_key(
        'image_hits_image_id_fkey_secure', 'image_hits', 'image', ['image_id'], ['id'], ondelete='CASCADE'
    )
    _create_index_unless_present(
        inspector, 'image_hits', 'image_hits_image_date_idx', ['image_id', 'hit_date']
    )

    op.execute(sa.text('''
        DELETE FROM message
        WHERE image IS NULL OR NOT EXISTS (SELECT 1 FROM image WHERE image.id = message.image)
    '''))
    op.execute(sa.text('''
        UPDATE message
        SET text = COALESCE(text, ''), message_date = COALESCE(message_date, CURRENT_TIMESTAMP)
    '''))
    op.alter_column('message', 'image', existing_type=sa.Integer(), nullable=False)
    op.alter_column('message', 'text', existing_type=sa.String(500), nullable=False)
    op.alter_column('message', 'message_date', existing_type=sa.DateTime(timezone=True), nullable=False)
    _create_index_unless_present(inspector, 'message', 'message_image_date_idx', ['image', 'message_date'])

    if 'audit_event' not in inspector.get_table_names():
        op.create_table(
            'audit_event',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('actor_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL')),
            sa.Column('action', sa.String(64), nullable=False),
            sa.Column('object_type', sa.String(64), nullable=False),
            sa.Column('object_id', sa.String(200), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index('audit_event_date_idx', 'audit_event', ['created_at'])


def _create_index_unless_present(inspector, table, name, columns, unique=False):
    if name not in {index['name'] for index in inspector.get_indexes(table)}:
        op.create_index(name, table, columns, unique=unique)


def downgrade():
    raise RuntimeError('The secure baseline is irreversible; restore the verified pre-migration backup.')
