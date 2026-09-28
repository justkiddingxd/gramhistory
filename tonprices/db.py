import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path


DEFAULT_DB = Path(__file__).resolve().parents[2] / 'ton-prices.sqlite3'


def db_path():
    return Path(os.environ.get('TONPRICES_DB', str(DEFAULT_DB))).resolve()


def connect(path=None, readonly=True, check_same_thread=True):
    path = Path(path or db_path()).resolve()
    if readonly:
        conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5, check_same_thread=check_same_thread)
        conn.execute('PRAGMA query_only=ON')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=30)
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=FULL')
    conn.row_factory = sqlite3.Row
    return conn


class ReadSnapshotCache:
    """Bounded aggregate cache invalidated by SQLite commits, never a time-based TTL."""
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.connection = None
        self.identity = None
        self.version = None
        self.values = {}

    def _close(self):
        if self.connection is not None:
            self.connection.close()
        self.connection = None
        self.version = None
        self.values.clear()

    def close(self):
        with self.lock:
            self._close()

    @contextmanager
    def snapshot(self):
        with self.lock:
            try:
                stat = self.path.stat()
                identity = (stat.st_dev, stat.st_ino)
                if self.connection is None or identity != self.identity:
                    self._close()
                    self.connection = connect(self.path, check_same_thread=False)
                    self.identity = identity
                connection = self.connection
                connection.execute('BEGIN')
                # Establish the read snapshot before checking its commit version.
                connection.execute('SELECT key FROM metadata LIMIT 1').fetchone()
                version = connection.execute('PRAGMA data_version').fetchone()[0]
                if version != self.version:
                    self.values.clear()
                    self.version = version
                yield connection, self.values
                connection.rollback()
            except OSError as error:
                self._close()
                raise sqlite3.OperationalError('Database file is unavailable') from error
            except BaseException:
                self._close()
                raise


LIVE_TABLE = '''
CREATE TABLE IF NOT EXISTS live_prices(
 id INTEGER PRIMARY KEY,
 series_id TEXT NOT NULL CHECK(series_id IN ('calcmula-usdt','calcmula-usd')),
 source TEXT NOT NULL CHECK(source='calcmula'),
 sample_bucket INTEGER NOT NULL,
 observed_at INTEGER NOT NULL,
 received_at TEXT NOT NULL,
 price TEXT NOT NULL,
 quote_currency TEXT NOT NULL CHECK(quote_currency IN ('USDT','USD')),
 expression TEXT NOT NULL,
 response_json TEXT NOT NULL,
 http_date TEXT,
 provider_updated_at INTEGER,
 UNIQUE(series_id,sample_bucket),
 CHECK((series_id='calcmula-usd' AND quote_currency='USD' AND expression='1 ton in usd')
    OR (series_id='calcmula-usdt' AND quote_currency='USDT' AND expression='1 ton in usdt')),
 CHECK(observed_at>=sample_bucket AND observed_at<sample_bucket+300)
);
'''

OBSERVATIONS_VIEW = '''
CREATE VIEW IF NOT EXISTS price_observations AS
 SELECT id,series_id,channel_id,message_id,observed_at,received_at,price,quote_currency,quote_basis,source,edited_at,
 'telegram_snapshot' AS kind,'message_time' AS timestamp_basis,NULL AS provider_updated_at,NULL AS expression
 FROM prices
 UNION ALL
 SELECT id,series_id,NULL AS channel_id,id AS message_id,observed_at,received_at,price,quote_currency,
 'provider_conversion' AS quote_basis,source,NULL AS edited_at,'api_snapshot' AS kind,
 'retrieval_time' AS timestamp_basis,provider_updated_at,expression FROM live_prices;
'''

SCHEMA = '''
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS raw_messages(
 channel_id INTEGER NOT NULL,
 message_id INTEGER NOT NULL,
 posted_at INTEGER,
 edited_at INTEGER,
 message_type TEXT NOT NULL,
 text TEXT NOT NULL,
 parse_status TEXT NOT NULL,
 raw_json_zlib BLOB NOT NULL,
 PRIMARY KEY(channel_id,message_id)
);
CREATE TABLE IF NOT EXISTS prices(
 id INTEGER PRIMARY KEY,
 series_id TEXT NOT NULL,
 channel_id INTEGER NOT NULL,
 message_id INTEGER NOT NULL,
 observed_at INTEGER NOT NULL,
 received_at TEXT NOT NULL,
 price TEXT NOT NULL,
 quote_currency TEXT NOT NULL CHECK(quote_currency='USD'),
 quote_basis TEXT NOT NULL CHECK(quote_basis='channel_label'),
 source TEXT NOT NULL CHECK(source='telegram'),
 edited_at INTEGER,
 UNIQUE(channel_id,message_id),
 FOREIGN KEY(channel_id,message_id) REFERENCES raw_messages(channel_id,message_id)
);
CREATE INDEX IF NOT EXISTS prices_series_time ON prices(series_id,observed_at DESC,message_id DESC);
''' + LIVE_TABLE + '''
CREATE INDEX IF NOT EXISTS live_prices_series_time ON live_prices(series_id,observed_at DESC,id DESC);
CREATE TABLE IF NOT EXISTS collector_state(
 name TEXT PRIMARY KEY,
 lease_owner TEXT,
 lease_until INTEGER,
 last_attempt_at INTEGER,
 last_success_at INTEGER,
 last_error TEXT,
 consecutive_failures INTEGER NOT NULL DEFAULT 0
);
''' + OBSERVATIONS_VIEW


def metadata(conn):
    return dict(conn.execute('SELECT key,value FROM metadata'))


def migrate_live(path):
    """Add live tables; the original 451k-row archive is never rebuilt or edited."""
    if not Path(path).is_file():
        raise ValueError('Existing imported database is required')
    conn = connect(path, readonly=False)
    try:
        if metadata(conn).get('import_state') != 'complete':
            raise ValueError('Archive import is incomplete')
        conn.executescript(SCHEMA)
        conn.execute('BEGIN IMMEDIATE')
        definition = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='live_prices'").fetchone()[0]
        if "'calcmula-usd'" not in definition:
            # Rebuild only the small live table, preserving every original field and ID.
            # DDL and data move commit together; a failure leaves the old schema intact.
            conn.execute('DROP VIEW IF EXISTS price_observations')
            conn.execute(LIVE_TABLE.replace('IF NOT EXISTS live_prices', 'live_prices_usd_migration'))
            columns = 'id,series_id,source,sample_bucket,observed_at,received_at,price,quote_currency,expression,response_json,http_date,provider_updated_at'
            conn.execute(f'INSERT INTO live_prices_usd_migration({columns}) SELECT {columns} FROM live_prices')
            conn.execute('DROP TABLE live_prices')
            conn.execute('ALTER TABLE live_prices_usd_migration RENAME TO live_prices')
            conn.execute('CREATE INDEX live_prices_series_time ON live_prices(series_id,observed_at DESC,id DESC)')
            conn.execute(OBSERVATIONS_VIEW)
        conn.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', ('schema_version', '3'))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

