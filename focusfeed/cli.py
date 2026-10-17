"""Command-line tools for the team, run with `flask --app run <command>`."""

import json
import os
import time
import sqlite3
from pathlib import Path

import click
from flask import current_app
from flask.cli import with_appcontext

from .db import get_db
from .services import account, clock, login_limits


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


@click.group("users")
def users_group():
    """Help a student who is locked out (they may have lost their recovery key)."""


def find_or_fail(db, username):
    user = account.find_user(db, username)
    if user is None:
        raise click.ClickException(f"No account called {username!r}.")
    return user


def unlock(db, username):
    login_limits.clear_failures(db, username.lower())
    login_limits.clear_failures(db, "reset:" + username.lower())


@users_group.command("set-password")
@click.argument("username")
@with_appcontext
def set_password_command(username):
    """Set a new password and sign the account out everywhere."""
    db = get_db()
    user = find_or_fail(db, username)
    password = click.prompt("New password", hide_input=True, confirmation_prompt=True)
    error = account.password_error(password)
    if error:
        raise click.ClickException(error)
    account.set_password(db, user["id"], password)
    unlock(db, user["username"])
    click.echo(f"Password changed for {user['username']}. They are signed out everywhere.")


@users_group.command("unlock")
@click.argument("username")
@with_appcontext
def unlock_command(username):
    """Clear failed sign-in and reset attempts so they can try again now."""
    db = get_db()
    user = find_or_fail(db, username)
    unlock(db, user["username"])
    click.echo(f"Unlocked {user['username']}.")


@users_group.command("delete")
@click.argument("username")
@click.option("--yes", is_flag=True, help="Don't ask for confirmation.")
@with_appcontext
def delete_command(username, yes):
    """Delete an account and everything stored about it (for a guardian's request)."""
    db = get_db()
    user = find_or_fail(db, username)
    if not yes:
        click.confirm(f"Delete {user['username']} and all their data? This can't be undone", abort=True)
    account.delete_user(db, user["id"])
    click.echo(f"Deleted {user['username']}.")


@users_group.command("export")
@click.argument("username")
@click.option("-o", "--output", type=click.Path(dir_okay=False, writable=True), help="File to write (default: print it).")
@with_appcontext
def export_command(username, output):
    """Write everything stored about an account as JSON."""
    db = get_db()
    user = find_or_fail(db, username)
    text = json.dumps(account.export_user(db, user["id"], time.time()), indent=2, ensure_ascii=False)
    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        click.echo(f"Wrote {output}")
    else:
        click.echo(text)


def init_app(app):
    app.cli.add_command(backup_command)
    app.cli.add_command(users_group)
