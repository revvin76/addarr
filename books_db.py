"""
books_db.py — Local SQLite database for book metadata.

The local DB is the app's primary source of truth.  External services
(Goodreads / Readarr) are only consulted when a book has no record here,
and the result is written back so subsequent loads are instant.

Schema key
----------
source  : where the metadata came from
  'file'       — extracted from the file itself (EPUB OPF / PDF info)
  'filename'   — title guessed from the filename (nothing richer found yet)
  'goodreads'  — enriched from Goodreads via Apify
  'readarr'    — enriched from Readarr API
  'manual'     — entered by the user via the import dialog
  'unknown'    — placeholder, enrichment pending
"""

import sqlite3
import os
import logging
from datetime import datetime

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(_APP_DIR, 'metadata', 'books.db')


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the books table if it doesn't exist yet, then migrate."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path       TEXT UNIQUE NOT NULL,
                title           TEXT,
                author          TEXT,
                cover_url       TEXT,
                overview        TEXT,
                year            INTEGER,
                pages           INTEGER,
                isbn            TEXT,
                goodreads_id    TEXT,
                foreign_book_id TEXT,
                internal_id     INTEGER,
                source          TEXT DEFAULT 'unknown',
                genre           TEXT,
                reading_status  TEXT DEFAULT 'not_started',
                is_wishlist     INTEGER DEFAULT 0,
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            )
        """)
        # ── Migrate existing databases — ADD COLUMN is idempotent via try/except ──
        for col, defn in [
            ('genre',          'TEXT'),
            ('reading_status', "TEXT DEFAULT 'not_started'"),
            ('is_wishlist',    'INTEGER DEFAULT 0'),
        ]:
            try:
                conn.execute(f'ALTER TABLE books ADD COLUMN {col} {defn}')
            except Exception:
                pass  # column already exists — normal on re-run
        conn.commit()
    logging.debug("[books_db] DB initialised at %s", DB_PATH)


def get_book_by_path(file_path):
    """Return a book dict for the given file path, or None."""
    with _connect() as conn:
        row = conn.execute(
            'SELECT * FROM books WHERE file_path = ?', (file_path,)
        ).fetchone()
        return dict(row) if row else None


def get_book_by_id(db_id):
    """Return a book dict by local DB id."""
    with _connect() as conn:
        row = conn.execute(
            'SELECT * FROM books WHERE id = ?', (db_id,)
        ).fetchone()
        return dict(row) if row else None


def get_book_by_foreign_id(foreign_book_id):
    """Return a book dict by Readarr/remote foreign book id."""
    with _connect() as conn:
        row = conn.execute(
            'SELECT * FROM books WHERE foreign_book_id = ?',
            (str(foreign_book_id),)
        ).fetchone()
        return dict(row) if row else None


def get_book_by_internal_id(internal_id):
    """Return a book dict by Readarr internal integer id."""
    with _connect() as conn:
        row = conn.execute(
            'SELECT * FROM books WHERE internal_id = ?',
            (internal_id,)
        ).fetchone()
        return dict(row) if row else None


def get_books_by_paths(file_paths):
    """Batch lookup by file path.  Returns {file_path: book_dict}."""
    if not file_paths:
        return {}
    placeholders = ','.join('?' * len(file_paths))
    with _connect() as conn:
        rows = conn.execute(
            f'SELECT * FROM books WHERE file_path IN ({placeholders})',
            list(file_paths)
        ).fetchall()
    return {row['file_path']: dict(row) for row in rows}


def save_book(data):
    """Insert or update a book record.  `data` must contain `file_path`.

    Only non-None values in `data` are written; existing fields not present
    in `data` are left untouched on updates.  Returns the updated book dict.
    """
    if 'file_path' not in data:
        raise ValueError("save_book: data must include 'file_path'")

    file_path = data['file_path']
    now = datetime.utcnow().isoformat()

    with _connect() as conn:
        existing = conn.execute(
            'SELECT id FROM books WHERE file_path = ?', (file_path,)
        ).fetchone()

        if existing:
            fields = {k: v for k, v in data.items()
                      if k not in ('id', 'file_path', 'created_at') and v is not None}
            fields['updated_at'] = now
            if fields:
                set_clause = ', '.join(f'{k} = ?' for k in fields)
                values     = list(fields.values()) + [file_path]
                conn.execute(
                    f'UPDATE books SET {set_clause} WHERE file_path = ?', values
                )
        else:
            row = {k: v for k, v in data.items() if v is not None}
            row.setdefault('created_at', now)
            row['updated_at'] = now
            cols         = ', '.join(row.keys())
            placeholders = ', '.join('?' * len(row))
            conn.execute(
                f'INSERT INTO books ({cols}) VALUES ({placeholders})',
                list(row.values())
            )
        conn.commit()

    return get_book_by_path(file_path)


def delete_book_by_path(file_path):
    """Remove a book record (does NOT delete the file)."""
    with _connect() as conn:
        conn.execute('DELETE FROM books WHERE file_path = ?', (file_path,))
        conn.commit()


def get_all_books():
    """Return all books ordered by title."""
    with _connect() as conn:
        rows = conn.execute(
            'SELECT * FROM books ORDER BY title COLLATE NOCASE'
        ).fetchall()
        return [dict(r) for r in rows]
