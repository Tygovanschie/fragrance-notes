#!/usr/bin/env python3
"""Nightly backup of the price database. Runs on the host (cron), not inside the API container.

Makes a consistent copy with SQLite's own backup API (safe while the API keeps writing), checks it
(integrity_check + reports table row count), stores it as backups/prices-YYYY-MM-DD.db (mode 600),
keeps the newest BACKUP_KEEP (7) and deletes older ones. Prints one line per run; under cron it
runs through `systemd-cat -t fragrance-backup`, so results show up in `journalctl -t fragrance-backup`
and a failure (stderr, exit 1) is logged at error priority.
"""
import datetime
import os
import re
import sqlite3
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("DB_PATH", os.path.join(BASE, "data", "prices.db"))
DIR = os.environ.get("BACKUP_DIR", os.path.join(BASE, "backups"))
KEEP = int(os.environ.get("BACKUP_KEEP", "7"))
NAME = re.compile(r"^prices-\d{4}-\d{2}-\d{2}\.db$")


def main():
    if not os.path.isfile(SRC):   # sqlite3.connect would silently create an empty database
        raise RuntimeError(f"database not found: {SRC}")
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    dest = os.path.join(DIR, f"prices-{datetime.date.today().isoformat()}.db")
    tmp = dest + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)

    old_umask = os.umask(0o077)
    try:
        src = sqlite3.connect(SRC, timeout=30)
        out = sqlite3.connect(tmp)
        src.backup(out)                                  # consistent snapshot, even mid-write
        out.execute("PRAGMA journal_mode=DELETE")        # a single self-contained file, no -wal/-shm
        out.close()
        src.close()
    finally:
        os.umask(old_umask)

    chk = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
    try:
        integrity = chk.execute("PRAGMA integrity_check").fetchone()[0]
        rows = chk.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        perfumes = chk.execute("SELECT COUNT(DISTINCT perfume_id) FROM reports").fetchone()[0]
    finally:
        chk.close()
    if integrity != "ok":
        os.remove(tmp)
        raise RuntimeError(f"integrity_check failed: {integrity}")
    os.replace(tmp, dest)
    os.chmod(dest, 0o600)

    backups = sorted(f for f in os.listdir(DIR) if NAME.match(f))
    removed = backups[:-KEEP] if len(backups) > KEEP else []
    for f in removed:
        os.remove(os.path.join(DIR, f))
    print(f"backup ok: {os.path.basename(dest)} rows={rows} perfumes={perfumes} "
          f"bytes={os.path.getsize(dest)} kept={len(backups) - len(removed)} removed={len(removed)}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"backup FAILED: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
