"""Publish consistent compressed SQLite snapshots outside the request process."""
import argparse
import gzip
import hashlib
import json
import logging
import os
import signal
import sqlite3
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from .db import connect, db_path, metadata

logger = logging.getLogger('tonprices.exporter')


def export_directory(database):
    return Path(os.environ.get('TONPRICES_EXPORT_DIR', str(Path(database).parent / 'exports'))).resolve()


def build_snapshot(database, directory, stop=None):
    """Backup includes committed WAL pages; publish the manifest only after success."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stop = stop or threading.Event()
    deadline = time.monotonic() + 120

    def progress(status, remaining, total):
        if stop.is_set() or time.monotonic() > deadline:
            raise InterruptedError('Snapshot backup interrupted')

    with tempfile.TemporaryDirectory(prefix='.building-', dir=directory) as temporary:
        temporary = Path(temporary)
        database_copy = temporary / 'prices.sqlite3'
        source = connect(database)
        try:
            if metadata(source).get('import_state') != 'complete':
                raise ValueError('Archive import has not completed')
            target = sqlite3.connect(database_copy)
            try:
                source.backup(target, pages=256, progress=progress, sleep=0.05)
                target.execute('PRAGMA journal_mode=DELETE')
                if target.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('Snapshot integrity check failed')
                counts = {table: target.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                          for table in ('prices', 'live_prices', 'raw_messages')}
            finally:
                target.close()
        finally:
            source.close()
        created = datetime.now(UTC).isoformat().replace('+00:00', 'Z')
        compressed = temporary / 'snapshot.gz'
        with database_copy.open('rb') as source_file, compressed.open('wb') as destination:
            with gzip.GzipFile(filename='', fileobj=destination, mode='wb', compresslevel=1, mtime=0) as archive:
                while chunk := source_file.read(1024 * 1024):
                    if stop.is_set():
                        raise InterruptedError('Snapshot compression interrupted')
                    archive.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        with compressed.open('rb') as content:
            checksum = hashlib.file_digest(content, 'sha256').hexdigest()
        filename = f'{checksum}.sqlite3.gz'
        result = {'file': filename, 'sha256': checksum, 'bytes': compressed.stat().st_size,
                  'created_at': created, 'counts': counts}
        previous = None
        try:
            previous = json.loads((directory / 'snapshot.json').read_text())['file']
        except (OSError, ValueError, KeyError):
            pass
        os.replace(compressed, directory / filename)
        manifest = temporary / 'snapshot.json'
        with manifest.open('w', encoding='utf8') as output:
            json.dump(result, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(manifest, directory / 'snapshot.json')
        # Open downloads keep their own file descriptor on Linux after unlink.
        for obsolete in directory.glob('*.sqlite3.gz'):
            if obsolete.name not in (filename, previous):
                try:
                    obsolete.unlink()
                except OSError:
                    logger.warning('Could not remove an old snapshot')
        return result


def main():
    parser = argparse.ArgumentParser(description='Create a complete SQLite gzip download without blocking API requests.')
    parser.add_argument('--db', type=Path, default=db_path())
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--loop', action='store_true')
    args = parser.parse_args()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    directory = args.directory or export_directory(args.db)
    while not stop.is_set():
        started = time.monotonic()
        try:
            snapshot = build_snapshot(args.db, directory, stop)
            print(json.dumps({'status': 'published', **snapshot}), flush=True)
        except InterruptedError:
            if stop.is_set():
                break
            logger.exception('Snapshot timed out; retaining the previous export')
        except Exception:
            logger.exception('Snapshot failed; retaining the previous export')
            if not args.loop:
                raise SystemExit(1)
        if not args.loop:
            return
        stop.wait(max(1, 300 - (time.monotonic() - started)))


if __name__ == '__main__':
    main()
