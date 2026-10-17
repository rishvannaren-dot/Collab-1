"""Command-line tools for the team, run with `flask --app run <command>`."""

import os
import sqlite3
from pathlib import Path

import click
from flask import current_app
from flask.cli import with_appcontext

from .services import clock


def backup_db(src_path, dest_dir, day, keep):
    """Save a dated copy of the database and keep only the newest `keep` copies.

    Uses SQLite's backup API, which is safe while the app is running (copying
    the file is not, because recent writes may still be in the -wal file).
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"focusfeed-{day.isoformat()}.db"
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.chmod(target, 0o600)
    copies = sorted(dest_dir.glob("focusfeed-*.db"))  # ISO dates sort by age
    for old in copies[:-keep]:
        old.unlink()
    return target


@click.command("backup")
@click.option("--dest", default=None, help="Folder for the copies (default: instance/backups).")
@click.option("--keep", default=7, show_default=True, type=click.IntRange(min=1))
@with_appcontext
def backup_command(dest, keep):
    """Save a dated copy of the database."""
    dest = dest or os.path.join(current_app.instance_path, "backups")
    day = clock.today(current_app.config["APP_TIMEZONE"])
    target = backup_db(current_app.config["DATABASE"], dest, day, keep)
    click.echo(f"Saved {target}")


def init_app(app):
    app.cli.add_command(backup_command)
