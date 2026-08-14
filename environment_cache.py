import hashlib
import json
import pickle
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
if not (ROOT_DIR / "config.py").exists():
    ROOT_DIR = Path(__file__).resolve().parents[1]

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


CACHE_DB = ROOT_DIR / "DB" / "environment_map_cache.db"
CACHE_VERSION = "environment-cache-v1"


def initialise_cache():
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(CACHE_DB, timeout=60) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_entries (
                namespace TEXT NOT NULL,
                cache_key TEXT NOT NULL,
                input_fingerprint TEXT NOT NULL,
                payload BLOB NOT NULL,
                updated_at_utc TEXT NOT NULL,
                PRIMARY KEY (namespace, cache_key)
            )
            """
        )


def make_fingerprint(value):
    """Return a deterministic SHA-256 fingerprint for JSON-compatible data."""
    encoded = json.dumps(
        value,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def get_cached_value(namespace, cache_key, input_fingerprint):
    initialise_cache()

    with sqlite3.connect(CACHE_DB, timeout=60) as connection:
        row = connection.execute(
            """
            SELECT payload
            FROM cache_entries
            WHERE namespace = ?
              AND cache_key = ?
              AND input_fingerprint = ?
            """,
            (namespace, cache_key, input_fingerprint),
        ).fetchone()

    if row is None:
        return None

    try:
        return pickle.loads(row[0])
    except Exception:
        delete_cached_value(namespace, cache_key)
        return None


def set_cached_value(namespace, cache_key, input_fingerprint, value):
    initialise_cache()
    payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)

    with sqlite3.connect(CACHE_DB, timeout=60) as connection:
        connection.execute(
            """
            INSERT INTO cache_entries (
                namespace,
                cache_key,
                input_fingerprint,
                payload,
                updated_at_utc
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(namespace, cache_key) DO UPDATE SET
                input_fingerprint = excluded.input_fingerprint,
                payload = excluded.payload,
                updated_at_utc = excluded.updated_at_utc
            """,
            (
                namespace,
                cache_key,
                input_fingerprint,
                sqlite3.Binary(payload),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def delete_cached_value(namespace, cache_key):
    initialise_cache()
    with sqlite3.connect(CACHE_DB, timeout=60) as connection:
        connection.execute(
            "DELETE FROM cache_entries WHERE namespace = ? AND cache_key = ?",
            (namespace, cache_key),
        )


def cache_entry_exists(namespace, cache_key, input_fingerprint):
    initialise_cache()
    with sqlite3.connect(CACHE_DB, timeout=60) as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM cache_entries
            WHERE namespace = ?
              AND cache_key = ?
              AND input_fingerprint = ?
            """,
            (namespace, cache_key, input_fingerprint),
        ).fetchone()
    return row is not None


def get_cache_counts():
    initialise_cache()
    with sqlite3.connect(CACHE_DB, timeout=60) as connection:
        return dict(
            connection.execute(
                """
                SELECT namespace, COUNT(*)
                FROM cache_entries
                GROUP BY namespace
                ORDER BY namespace
                """
            ).fetchall()
        )


def list_cache_entries(namespace=None):
    """Return cache metadata without loading the pickled payloads."""
    initialise_cache()
    query = """
        SELECT
            namespace,
            cache_key,
            input_fingerprint,
            LENGTH(payload) AS payload_bytes,
            updated_at_utc
        FROM cache_entries
    """
    params = ()

    if namespace:
        query += " WHERE namespace = ?"
        params = (namespace,)

    query += " ORDER BY updated_at_utc DESC, namespace, cache_key"

    with sqlite3.connect(CACHE_DB, timeout=60) as connection:
        connection.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in connection.execute(query, params).fetchall()
        ]


def delete_cache_entries(namespace, cache_keys=None):
    """Delete a namespace or selected keys and return the removed row count."""
    initialise_cache()

    with sqlite3.connect(CACHE_DB, timeout=60) as connection:
        if cache_keys:
            placeholders = ", ".join("?" for _ in cache_keys)
            cursor = connection.execute(
                f"""
                DELETE FROM cache_entries
                WHERE namespace = ?
                  AND cache_key IN ({placeholders})
                """,
                (namespace, *cache_keys),
            )
        else:
            cursor = connection.execute(
                "DELETE FROM cache_entries WHERE namespace = ?",
                (namespace,),
            )

    return max(int(cursor.rowcount), 0)


def clear_cache():
    """Delete every cache entry and return the removed row count."""
    initialise_cache()
    with sqlite3.connect(CACHE_DB, timeout=60) as connection:
        cursor = connection.execute("DELETE FROM cache_entries")
    return max(int(cursor.rowcount), 0)


def vacuum_cache():
    """Compact the cache database after entries have been removed."""
    initialise_cache()
    with sqlite3.connect(CACHE_DB, timeout=60) as connection:
        connection.execute("VACUUM")