from logging.config import fileConfig

from alembic import context
from flask import current_app

config = context.config
fileConfig(config.config_file_name)
database_url = current_app.extensions['migrate'].db.engine.url.render_as_string(hide_password=False)
config.set_main_option('sqlalchemy.url', database_url.replace('%', '%%'))
target_metadata = current_app.extensions['migrate'].db.metadata


def run_migrations_offline():
    context.configure(
        url=config.get_main_option('sqlalchemy.url'),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with current_app.extensions['migrate'].db.engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
