import sqlite3

import click
from flask import current_app, g

from . import migrations


def connect(path):
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    # Off by default in SQLite; must be set on every connection.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(e=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    """Create missing tables and apply pending migrations. Safe to repeat."""
    db = get_db()
    with current_app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf-8"))
    if current_app.config["DATABASE"] != ":memory:":
        # Lets pages read while another request is writing.
        db.execute("PRAGMA journal_mode = WAL")
    migrations.migrate(db)


@click.command("init-db")
def init_db_command():
    """Create the database tables."""
    init_db()
    click.echo("Initialized the database.")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
