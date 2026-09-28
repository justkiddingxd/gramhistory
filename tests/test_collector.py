import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tonprices.app import create_app
from tonprices.collector import EXPRESSION, ProviderError, collect_once, decode_quote
from tonprices.db import connect, migrate_live
from tonprices.importer import import_export


NOW = 1790490000  # 2026-09-27, deterministic test time


def response(amount='1.5904150983406669', **changes):
    raw = '{"ok":true,"expression":"1 ton in usd","result":{"type":"value","amount":' + amount + ',"currency":"usd"},"currencies":["gram","usd"],"warnings":[]}'
    if changes:
        payload = json.loads(raw)
        payload.update(changes)
        raw = json.dumps(payload)
    return raw.encode(), {'Content-Type': 'application/json'}


@pytest.fixture
def database(tmp_path):
    source = tmp_path/'messages.json'
    db = tmp_path/'db.sqlite3'
    source.write_text(json.dumps({'id':123,'name':'Test','type':'public_channel','messages':[
        {'id':1,'type':'message','date_unixtime':str(NOW-200),'text':'2.00$'},
        {'id':2,'type':'message','date_unixtime':str(NOW-100),'text':'2.01$'},
    ]}))
    import_export(source,db)
    return db


def test_precision_deduplication_and_unchanged_price_next_interval(database):
    calls = []
    def fetch():
        calls.append(True)
        return response()
    result = collect_once(database, fetch=fetch, clock=lambda:NOW+10)
    assert result['price'] == '1.5904150983406669'
    assert result['status'] == 'inserted'
    assert collect_once(database, fetch=fetch, clock=lambda:NOW+20)['status'] == 'already_recorded'
    assert len(calls) == 1
    assert collect_once(database, fetch=fetch, clock=lambda:NOW+310)['status'] == 'inserted'
    conn=connect(database)
    try:
        assert conn.execute('SELECT count(*) FROM live_prices').fetchone()[0] == 2
        assert conn.execute('SELECT count(*) FROM prices').fetchone()[0] == 2
        assert conn.execute('SELECT value FROM metadata WHERE key=?', ('calcmula_cutover_at',)).fetchone()[0] == str(NOW+10)
    finally: conn.close()


@pytest.mark.parametrize('body,headers', [
    (b'<html>wrong route</html>', {'Content-Type':'text/html'}),
    response('-1'), response('0'), response('true'), response('NaN'), response('1e-100'),
    response(ok=False), response(expression='1 btc in usd'), response(warnings=[{'code':'unexpected'}]),
    (response()[0], {'Content-Type':'application/json','Age':'301'}),
    (response()[0], {'Content-Type':'application/json','Date':'Wed, 01 Jan 2020 00:00:00 GMT'}),
    (response()[0].replace(b'"currency":"usd"',b'"currency":"usdt"'), {'Content-Type':'application/json'}),
])
def test_reject_bad_provider_responses(body,headers):
    with pytest.raises(ProviderError): decode_quote(body,headers,NOW)


def test_provider_failure_does_not_insert_and_can_recover(database):
    def fail(): raise ProviderError('Network unavailable')
    with pytest.raises(ProviderError): collect_once(database,fetch=fail,clock=lambda:NOW+10)
    conn=connect(database)
    try:
        assert conn.execute('SELECT count(*) FROM live_prices').fetchone()[0] == 0
        state=conn.execute('SELECT * FROM collector_state').fetchone()
        assert state['consecutive_failures'] == 1 and state['lease_owner'] is None
        assert conn.execute('SELECT value FROM metadata WHERE key=?',('calcmula_cutover_at',)).fetchone() is None
    finally: conn.close()
    assert collect_once(database,fetch=lambda:response(),clock=lambda:NOW+20)['status'] == 'inserted'


def test_overlapping_worker_uses_lease(database):
    results=[]
    def fetch():
        results.append(collect_once(database,fetch=lambda:response(),clock=lambda:NOW+11))
        return response()
    collect_once(database,fetch=fetch,clock=lambda:NOW+10)
    assert results == [{'status':'busy'}]


def test_cutover_latest_history_and_daily_keep_currency_distinct(database):
    collect_once(database,fetch=lambda:response(),clock=lambda:NOW+10)
    client=TestClient(create_app(database,clock=lambda:NOW+60))
    latest=client.get('/v1/ton/price/latest')
    assert latest.status_code == 200
    data=latest.json()['data']
    assert data['source']['provider'] == 'calcmula'
    assert data['quote_currency'] == 'USD'
    assert data['timestamp_basis'] == 'retrieval_time'
    assert data['provider_updated_at'] is None
    assert 'USD_LABEL_UNVERIFIED' not in [w['code'] for w in latest.json()['meta']['warnings']]
    before=datetime.fromtimestamp(NOW-1).astimezone().isoformat()
    historic=client.get('/v1/ton/price',params={'at':before})
    assert historic.json()['data']['quote_currency'] == 'USD'
    utc=lambda n:datetime.fromtimestamp(n, __import__('datetime').UTC).isoformat()
    history=client.get('/v1/ton/history',params={'from':utc(NOW-300),'to':utc(NOW+60)})
    assert [point['quote_currency'] for point in history.json()['data']] == ['USD','USD','USD']
    day=datetime.fromtimestamp(NOW, __import__('datetime').UTC).date().isoformat()
    daily=client.get('/v1/ton/daily',params={'date':day})
    assert [segment['quote_currency'] for segment in daily.json()['data']['segments']] == ['USD','USD']
    assert client.get('/v1/ton/price',params={'at':day}).json()['data'] == daily.json()['data']
    coverage=client.get('/v1/ton/coverage').json()['data']
    assert len(coverage['segments']) == 2 and coverage['cutover_at']
    assert coverage['collector']['last_success_at'] == NOW+10


def test_coverage_cache_sees_commits_and_does_not_leak_between_series(database):
    with TestClient(create_app(database,clock=lambda:NOW+1000)) as client:
        assert client.get('/v1/ton/coverage').json()['data']['segments'][0]['points_count'] == 2
        assert client.get('/v1/ton/coverage',params={'series':'calcmula-usd'}).json()['data']['segments'] == []
        collect_once(database,fetch=lambda:response(),clock=lambda:NOW+10)
        result = client.get('/v1/ton/coverage').json()['data']
        assert [segment['points_count'] for segment in result['segments']] == [2,1]
        assert result['collector']['last_success_at'] == NOW+10
        collect_once(database,fetch=lambda:response(),clock=lambda:NOW+310)
        assert client.get('/v1/ton/coverage',params={'series':'calcmula-usd'}).json()['data']['segments'][0]['points_count'] == 2
        assert client.get('/v1/ton/coverage',params={'series':'telegram-usd'}).json()['data']['segments'][0]['points_count'] == 2


def test_reference_pagination_crosses_cutover_without_duplicates(database):
    collect_once(database,fetch=lambda:response(),clock=lambda:NOW+10)
    client=TestClient(create_app(database,clock=lambda:NOW+60))
    utc=lambda n:datetime.fromtimestamp(n, __import__('datetime').UTC).isoformat()
    params={'from':utc(NOW-300),'to':utc(NOW+60),'limit':1}
    values=[]
    while True:
        result=client.get('/v1/ton/history',params=params)
        assert result.status_code == 200
        body=result.json(); values.extend(p['price'] for p in body['data'])
        if not body['meta']['next_cursor']: break
        params['cursor']=body['meta']['next_cursor']
    assert values == ['2.00','2.01','1.5904150983406669']


def test_live_gap_does_not_fall_back_to_telegram(database):
    collect_once(database,fetch=lambda:response(),clock=lambda:NOW+10)
    client=TestClient(create_app(database,clock=lambda:NOW+2000))
    result=client.get('/v1/ton/price/latest')
    assert result.status_code == 503 and result.json()['code'] == 'PRICE_STALE'


def install_legacy_live_table(database, expression='1 ton in usdt'):
    with connect(database, readonly=False) as conn:
        conn.execute('DROP VIEW price_observations')
        conn.execute('DROP TABLE live_prices')
        conn.executescript((Path(__file__).parent/'fixtures/live-v2.sql').read_text())
        body = response()[0].replace(b'usd', b'usdt').decode()
        conn.execute('INSERT INTO live_prices VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (42, 'calcmula-usdt', 'calcmula', NOW, NOW+10, '2026-09-27T06:20:10Z',
             '1.600001234567890', 'USDT', expression, body, None, None))
        conn.execute("INSERT OR REPLACE INTO metadata VALUES('schema_version','2')")
        conn.execute("INSERT OR REPLACE INTO metadata VALUES('calcmula_cutover_at',?)", (str(NOW+10),))


def test_migration_preserves_legacy_rows_ids_and_is_idempotent(database):
    install_legacy_live_table(database)
    with connect(database) as conn:
        before = tuple(conn.execute('SELECT * FROM live_prices').fetchone())
        archive = [tuple(row) for row in conn.execute('SELECT * FROM prices')]
    migrate_live(database)
    migrate_live(database)
    with connect(database) as conn:
        assert tuple(conn.execute('SELECT * FROM live_prices').fetchone()) == before
        assert [tuple(row) for row in conn.execute('SELECT * FROM prices')] == archive
        assert conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0] == '3'
        assert conn.execute('SELECT count(*) FROM price_observations').fetchone()[0] == 3
        assert any(row['name'] == 'live_prices_series_time' for row in conn.execute('PRAGMA index_list(live_prices)'))
    # A USD observation can be stored in the same five-minute bucket as legacy USDT.
    assert collect_once(database, fetch=lambda:response(), clock=lambda:NOW+60)['status'] == 'inserted'
    assert collect_once(database, fetch=lambda:response(), clock=lambda:NOW+70)['status'] == 'already_recorded'
    with connect(database) as conn:
        assert conn.execute('SELECT quote_currency FROM live_prices WHERE id=42').fetchone()[0] == 'USDT'
        assert conn.execute('SELECT id FROM live_prices WHERE series_id=?', ('calcmula-usd',)).fetchone()[0] > 42


def test_failed_migration_rolls_back_schema_and_data(database):
    install_legacy_live_table(database, expression='unexpected legacy expression')
    with pytest.raises(sqlite3.IntegrityError):
        migrate_live(database)
    with connect(database) as conn:
        assert conn.execute('SELECT expression FROM live_prices WHERE id=42').fetchone()[0] == 'unexpected legacy expression'
        definition = conn.execute("SELECT sql FROM sqlite_master WHERE name='live_prices'").fetchone()[0]
        assert "'calcmula-usd'" not in definition
        assert conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0] == '2'


def test_usd_transition_boundaries_pagination_daily_and_cache(database):
    install_legacy_live_table(database)
    migrate_live(database)
    utc = lambda n: datetime.fromtimestamp(n, __import__('datetime').UTC).isoformat()
    with TestClient(create_app(database, clock=lambda:NOW+180)) as client:
        assert [s['quote_currency'] for s in client.get('/v1/ton/coverage').json()['data']['segments']] == ['USD','USDT']
        collect_once(database, fetch=lambda:response(), clock=lambda:NOW+60)
        for when, currency in [(NOW-1,'USD'),(NOW+10,'USDT'),(NOW+59,'USDT'),(NOW+60,'USD')]:
            result = client.get('/v1/ton/price', params={'at':utc(when)})
            assert result.status_code == 200
            assert result.json()['data']['quote_currency'] == currency
        latest = client.get('/v1/ton/price/latest').json()
        assert latest['data']['quote_currency'] == 'USD'
        assert latest['data']['source']['symbol'] == 'GRAM/USD'
        assert latest['meta']['policy_version'] == 'reference-calcmula-usd-v2'
        assert client.get('/v1/ton/price/latest',params={'series':'calcmula-usdt'}).json()['data']['quote_currency'] == 'USDT'
        assert client.get('/v1/ton/price',params={'at':utc(NOW+59),'series':'calcmula-usd'}).status_code == 404
        params={'from':utc(NOW-300),'to':utc(NOW+180),'limit':1}
        points=[]
        for _ in range(10):
            result=client.get('/v1/ton/history',params=params)
            assert result.status_code == 200
            body=result.json(); points.extend(body['data'])
            if not body['meta']['next_cursor']: break
            params['cursor']=body['meta']['next_cursor']
        else: pytest.fail('Pagination did not terminate')
        assert [p['quote_currency'] for p in points] == ['USD','USD','USDT','USD']
        day = datetime.fromtimestamp(NOW,__import__('datetime').UTC).date().isoformat()
        daily=client.get('/v1/ton/price',params={'at':day}).json()['data']
        assert [s['series'] for s in daily['segments']] == ['telegram-usd','calcmula-usdt','calcmula-usd']
        assert [s['points_count'] for s in daily['segments']] == [2,1,1]
        assert daily['segments'][1]['to'] == daily['segments'][2]['from'] == utc(NOW+60).replace('+00:00','Z')
        coverage=client.get('/v1/ton/coverage').json()['data']
        assert coverage['usd_cutover_at'] == utc(NOW+60).replace('+00:00','Z')
        assert [s['quote_currency'] for s in coverage['segments']] == ['USD','USDT','USD']
        assert client.get('/v1/ton/coverage',params={'series':'calcmula-usd'}).json()['data']['segments'][0]['points_count'] == 1
    stale=TestClient(create_app(database,clock=lambda:NOW+2000)).get('/v1/ton/price/latest')
    assert stale.status_code == 503 and stale.json()['code'] == 'PRICE_STALE'
