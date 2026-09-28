import gzip
import hashlib
import json
import sqlite3
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from tonprices.app import create_app
from tonprices.collector import collect_once
from tonprices.db import connect
from tonprices.download import download_snapshot
from tonprices.exporter import build_snapshot
from tonprices.importer import import_export


@pytest.fixture
def exported(tmp_path):
    database = tmp_path / 'prices.sqlite3'
    source = tmp_path / 'messages.json'
    source.write_text(json.dumps({'id': 123, 'name': 'Test', 'type': 'public_channel', 'messages': [
        {'id': 1, 'type': 'message', 'date_unixtime': '1707123300', 'text': '2.050000$'},
        {'id': 2, 'type': 'message', 'date_unixtime': '1707123600', 'text': '2.06$'},
    ]}))
    import_export(source, database)
    # Keep a connection open so the committed change really lives in the WAL.
    keeper = connect(database, readonly=False)
    keeper.execute('PRAGMA wal_autocheckpoint=0')
    body = b'{"ok":true,"expression":"1 ton in usd","result":{"type":"value","amount":1.5904150983406669,"currency":"usd"},"currencies":["gram","usd"],"warnings":[]}'
    collect_once(database, fetch=lambda: (body, {'Content-Type': 'application/json'}), clock=lambda: 1790490010)
    keeper.execute("INSERT INTO metadata VALUES('wal_marker','included')")
    keeper.commit()
    directory = tmp_path / 'exports'
    snapshot = build_snapshot(database, directory)
    now = datetime.fromisoformat(snapshot['created_at'].replace('Z', '+00:00')).timestamp()
    yield database, directory, snapshot, now
    keeper.close()


def test_complete_snapshot_includes_wal_precise_prices_and_raw_messages(exported, tmp_path):
    database, directory, snapshot, now = exported
    client = TestClient(create_app(database, exports=directory, clock=lambda: now))
    response = client.get('/v1/ton/export')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/gzip'
    assert 'content-encoding' not in response.headers
    assert response.headers['content-disposition'].endswith('.sqlite3.gz"')
    assert int(response.headers['content-length']) == len(response.content)
    assert hashlib.sha256(response.content).hexdigest() == response.headers['x-checksum-sha256']
    restored = tmp_path / 'restored.sqlite3'
    restored.write_bytes(gzip.decompress(response.content))
    conn = sqlite3.connect(restored)
    try:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
        assert conn.execute("SELECT value FROM metadata WHERE key='wal_marker'").fetchone()[0] == 'included'
        assert conn.execute('SELECT price FROM prices ORDER BY id').fetchall() == [('2.050000',), ('2.06',)]
        assert conn.execute('SELECT price,quote_currency FROM live_prices').fetchall() == [('1.5904150983406669', 'USD')]
        assert conn.execute('SELECT count(*) FROM raw_messages').fetchone()[0] == 2
        assert conn.execute('SELECT count(*) FROM price_observations').fetchone()[0] == 3
    finally:
        conn.close()


def test_download_metadata_and_conditional_requests(exported):
    database, directory, snapshot, now = exported
    client = TestClient(create_app(database, exports=directory, clock=lambda: now))
    metadata = client.head('/v1/ton/export')
    assert metadata.status_code == 200 and metadata.content == b''
    assert metadata.headers['x-snapshot-created-at'] == snapshot['created_at']
    assert int(metadata.headers['content-length']) == snapshot['bytes']
    assert metadata.headers['cache-control'] == 'public, max-age=60, must-revalidate'
    etag = metadata.headers['etag']
    for match in [etag, 'W/' + etag, '"different", ' + etag, '*']:
        result = client.get('/v1/ton/export', headers={'If-None-Match': match})
        assert result.status_code == 304 and result.content == b''
    assert client.get('/v1/ton/export', headers={'If-None-Match': '"different"'}).status_code == 200
    assert client.get('/health/live').headers['cache-control'] == 'no-store'
    schema = client.get('/openapi.json').json()['paths']['/v1/ton/export']['get']
    assert schema['responses']['200']['content']['application/gzip']['schema']['format'] == 'binary'


def test_missing_and_stale_export_keep_standard_errors(exported, tmp_path):
    database, directory, snapshot, now = exported
    for folder, clock, code in [(tmp_path/'missing', now, 'EXPORT_UNAVAILABLE'), (directory, now+901, 'EXPORT_STALE')]:
        client = TestClient(create_app(database, exports=folder, clock=lambda: clock))
        response = client.get('/v1/ton/export')
        assert response.status_code == 503
        assert response.headers['content-type'] == 'application/problem+json'
        assert response.headers['retry-after'] == '60'
        assert response.headers['cache-control'] == 'no-store'
        assert response.json()['code'] == code
        assert response.json()['request_id'] == response.headers['x-request-id']


def test_failed_rebuild_keeps_previous_snapshot(exported, monkeypatch):
    database, directory, snapshot, now = exported
    manifest = (directory/'snapshot.json').read_bytes()
    def fail(*args, **kwargs):
        raise OSError('Simulated full disk')
    monkeypatch.setattr(gzip.GzipFile, 'write', fail)
    with pytest.raises(OSError):
        build_snapshot(database, directory)
    assert (directory/'snapshot.json').read_bytes() == manifest
    assert (directory/snapshot['file']).is_file()
    assert list(directory.glob('.building-*')) == []


def test_in_progress_download_keeps_old_snapshot_after_new_publication(exported):
    database, directory, old, now = exported
    response = download_snapshot(directory, Request({'type': 'http', 'method': 'GET', 'headers': []}), now)
    try:
        for index in range(2):
            conn = connect(database, readonly=False)
            conn.execute('UPDATE prices SET price=? WHERE id=1', (str(10+index),))
            conn.commit()
            conn.close()
            build_snapshot(database, directory)
        assert hashlib.file_digest(response.file, 'sha256').hexdigest() == old['sha256']
    finally:
        response.file.close()


def test_corrupt_manifest_cannot_read_other_files(exported):
    database, directory, snapshot, now = exported
    snapshot['file'] = '../prices.sqlite3'
    (directory/'snapshot.json').write_text(json.dumps(snapshot))
    client = TestClient(create_app(database, exports=directory, clock=lambda: now))
    assert client.get('/v1/ton/export').json()['code'] == 'EXPORT_UNAVAILABLE'
