"""Streaming, resumable import of one immutable Telegram Desktop JSON export."""
import argparse
import hashlib
import json
import re
import zlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import ijson

from .db import SCHEMA, connect, metadata

PRICE_RE = re.compile(r'^\s*(\d+(?:[.,]\d+)?)\s*\$\s*$')


def flatten_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ''.join(flatten_text(item) for item in value)
    if isinstance(value, dict):
        return flatten_text(value.get('text', ''))
    return ''


def parse_price(text):
    match = PRICE_RE.fullmatch(text)
    if not match:
        return None
    value = match.group(1).replace(',', '.')
    if Decimal(value) <= 0:
        return None
    return value


def unix_time(value):
    # Never infer timezone from Telegram's naive local "date" field.
    if value is None or isinstance(value, bool):
        raise ValueError('Missing or invalid Unix timestamp')
    if not re.fullmatch(r'\d+', str(value)):
        raise ValueError('Invalid Unix timestamp')
    result = int(value)
    if not 0 < result < 4102444800:
        raise ValueError('Timestamp outside supported range')
    return result


def export_header(path):
    result = {}
    with open(path, 'rb') as stream:
        for prefix, event, value in ijson.parse(stream):
            if prefix == 'messages' and event == 'start_array':
                break
            if prefix in ('id', 'name', 'type') and event in ('string', 'number'):
                result[prefix] = value
    if result.get('type') != 'public_channel' or not isinstance(result.get('id'), int):
        raise ValueError('Expected Telegram public_channel export with integer id')
    return result


def fingerprint(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def import_export(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    before = source.stat()
    digest = fingerprint(source)
    header = export_header(source)
    conn = connect(destination, readonly=False)
    try:
        conn.executescript(SCHEMA)
        previous = metadata(conn)
        if previous.get('source_sha256') not in (None, digest):
            raise ValueError('This database belongs to another export. Use a new database to avoid silent history revisions.')
        if previous.get('import_state') == 'complete':
            return {'already_imported': True, 'prices': conn.execute('SELECT count(*) FROM prices').fetchone()[0], 'sha256': digest}
        imported_at = previous.get('imported_at', datetime.now(UTC).isoformat().replace('+00:00', 'Z'))
        values = {
            'source_sha256': digest, 'source_filename': source.name, 'source_size_bytes': str(before.st_size),
            'channel_id': str(header['id']), 'channel_name': header['name'], 'imported_at': imported_at,
            'import_state': 'running', 'schema_version': '1', 'parser_version': '1',
            'quote_basis': 'USD inferred from channel dollar sign, upstream denomination not independently verified',
        }
        conn.executemany('INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)', values.items())
        conn.commit()
        counts = {'total': 0, 'prices': 0, 'service': 0, 'non_price': 0, 'invalid_timestamp': 0, 'duplicates': 0}
        with open(source, 'rb') as stream:
            for message in ijson.items(stream, 'messages.item'):
                counts['total'] += 1
                message_id = message.get('id')
                if not isinstance(message_id, int) or message_id <= 0:
                    raise ValueError('Invalid message id')
                text = flatten_text(message.get('text', ''))
                price = parse_price(text) if message.get('type') == 'message' else None
                status = 'service' if message.get('type') == 'service' else ('price' if price else 'non_price')
                try:
                    timestamp = unix_time(message.get('date_unixtime'))
                except ValueError:
                    timestamp, price, status = None, None, 'invalid_timestamp'
                edited_at = unix_time(message['edited_unixtime']) if message.get('edited_unixtime') else None
                raw = zlib.compress(json.dumps(message, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf8'))
                inserted = conn.execute('INSERT OR IGNORE INTO raw_messages VALUES(?,?,?,?,?,?,?,?)',
                    (header['id'], message_id, timestamp, edited_at, message.get('type', 'unknown'), text, status, raw)).rowcount
                if not inserted:
                    existing = conn.execute('SELECT raw_json_zlib FROM raw_messages WHERE channel_id=? AND message_id=?', (header['id'], message_id)).fetchone()[0]
                    if existing != raw:
                        raise ValueError(f'Conflicting duplicate message {message_id}; import stopped')
                    counts['duplicates'] += 1
                if price is not None:
                    conn.execute('INSERT OR IGNORE INTO prices(series_id,channel_id,message_id,observed_at,received_at,price,quote_currency,quote_basis,source,edited_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                        ('telegram-usd', header['id'], message_id, timestamp, imported_at, price, 'USD', 'channel_label', 'telegram', edited_at))
                    counts['prices'] += 1
                else:
                    counts[status] += 1
                if counts['total'] % 10000 == 0:
                    conn.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', ('processed_messages', str(counts['total'])))
                    conn.commit()
                    print(json.dumps({'processed': counts['total'], 'prices': counts['prices']}), flush=True)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or fingerprint(source) != digest:
            raise ValueError('Source changed during import')
        conn.executemany('INSERT OR REPLACE INTO metadata VALUES(?,?)', [('import_state', 'complete'), ('import_counts', json.dumps(counts)), ('completed_at', datetime.now(UTC).isoformat())])
        conn.commit()
        conn.execute('ANALYZE')
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        return {**counts, 'sha256': digest}
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--db', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(import_export(args.source, args.db), indent=2))


if __name__ == '__main__':
    main()
