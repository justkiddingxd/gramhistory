import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from tonprices.app import create_app
from tonprices.db import DEFAULT_DB, SCHEMA, connect
from tonprices.importer import import_export, parse_price


def timestamp(value):
    return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp())


@pytest.fixture
def small_db(tmp_path):
    source, database = tmp_path/'export.json', tmp_path/'prices.sqlite3'
    messages = [
        {'id': 1, 'type': 'service', 'date_unixtime': str(timestamp('2024-02-05T08:50:00Z')), 'text': ''},
        {'id': 2, 'type': 'message', 'date_unixtime': str(timestamp('2024-02-05T08:55:00Z')), 'text': ['2.', {'text': '050000$'}]},
        {'id': 3, 'type': 'message', 'date_unixtime': str(timestamp('2024-02-05T09:00:00Z')), 'text': '2.06$'},
        {'id': 4, 'type': 'message', 'date_unixtime': str(timestamp('2024-02-05T11:00:00Z')), 'text': '2.10$'},
        {'id': 5, 'type': 'message', 'date_unixtime': str(timestamp('2024-02-05T11:00:00Z')), 'text': '2.11$'},
    ]
    source.write_text(json.dumps({'id': 123, 'name': 'Test', 'type': 'public_channel', 'messages': messages}), encoding='utf8')
    import_export(source, database)
    return source, database


@pytest.fixture
def client(small_db):
    return TestClient(create_app(small_db[1], clock=lambda: timestamp('2024-02-06T12:00:00Z')))


def test_exact_decimal_and_asof(client):
    result = client.get('/v1/ton/price', params={'at': '2024-02-05T08:59:59Z'})
    assert result.status_code == 200
    body = result.json()
    assert body['data']['price'] == '2.050000'
    assert body['data']['age_seconds'] == 299
    assert body['data']['quote_currency'] == 'USD'
    assert result.headers['X-Request-ID'] == body['meta']['request_id']
    assert body['data']['observed_at'] == '2024-02-05T08:55:00Z'


def test_same_second_is_deterministic(client):
    result = client.get('/v1/ton/price', params={'at': '2024-02-05T11:00:00Z', 'max_age_seconds': 0})
    assert result.json()['data']['price'] == '2.11'


@pytest.mark.parametrize('at,code,status', [
    ('2024-02-30', 'VALIDATION_ERROR', 422),
    ('2024-02-05T09:00:00', 'VALIDATION_ERROR', 422),
    ('2024-02-05T10:00:00Z', 'DATA_GAP', 404),
    ('2024-02-05T01:00:00Z', 'PRICE_NOT_FOUND', 404),
    ('2024-02-07T12:00:00Z', 'FUTURE_TIMESTAMP', 422),
])
def test_error_contract(client, at, code, status):
    result = client.get('/v1/ton/price', params={'at': at})
    assert result.status_code == status
    assert result.headers['content-type'] == 'application/problem+json'
    assert result.json()['status'] == status
    assert result.json()['code'] == code
    assert result.headers['x-request-id'] == result.json()['request_id']


def test_no_usd_fallback_for_usdt(client):
    result = client.get('/v1/ton/price', params={'at': '2024-02-05T09:00:00Z', 'series': 'market-usdt'})
    assert result.status_code == 404
    assert result.json()['code'] == 'PRICE_NOT_FOUND'


def test_stale_latest_and_missing_database(client, tmp_path):
    assert client.get('/v1/ton/price/latest').json()['code'] == 'PRICE_STALE'
    missing = TestClient(create_app(tmp_path/'missing.sqlite3'))
    assert missing.get('/health/live').status_code == 200
    assert missing.get('/health/ready').status_code == 503


def test_pagination_duplicate_timestamps_and_exclusive_end(client):
    filters = {'from': '2024-02-05T08:55:00Z', 'to': '2024-02-05T12:00:00Z', 'limit': 1}
    collected = []
    while True:
        result = client.get('/v1/ton/history', params=filters)
        assert result.status_code == 200
        body = result.json()
        collected.extend(p['price'] for p in body['data'])
        if not body['meta']['next_cursor']: break
        filters['cursor'] = body['meta']['next_cursor']
    assert collected == ['2.050000', '2.06', '2.10', '2.11']
    result = client.get('/v1/ton/history', params={'from':'2024-02-05T08:55:00Z','to':'2024-02-05T09:00:00Z'})
    assert len(result.json()['data']) == 1


def test_cursor_mismatch_invalid_range_and_limit(client):
    filters = {'from': '2024-02-05T08:55:00Z', 'to': '2024-02-05T12:00:00Z', 'limit': 1}
    cursor = client.get('/v1/ton/history', params=filters).json()['meta']['next_cursor']
    assert client.get('/v1/ton/history', params={**filters, 'limit': 2, 'cursor': cursor}).status_code == 422
    assert client.get('/v1/ton/history', params={**filters, 'cursor': '$not-base64'}).status_code == 422
    assert client.get('/v1/ton/history', params={**filters, 'limit': 1001}).status_code == 422
    assert client.get('/v1/ton/history', params={**filters, 'to': filters['from']}).status_code == 422


def test_daily_local_bounds_and_precision(client):
    result = client.get('/v1/ton/daily', params={'date': '2024-02-05', 'timezone': 'Europe/Moscow'})
    assert result.status_code == 200
    data = result.json()['data']
    assert data['from'] == '2024-02-04T21:00:00Z'
    assert data['to'] == '2024-02-05T21:00:00Z'
    assert data['segments'][0]['min'] == '2.050000'
    assert data['segments'][0]['max'] == '2.11'
    assert data['segments'][0]['points_count'] == 4
    assert data['segments'][0]['expected_points'] is None
    assert client.get('/v1/ton/daily', params={'date':'2024-02-05','timezone':'invalid'}).status_code == 422


def test_date_only_returns_daily_summary_and_keeps_exact_values(client):
    result = client.get('/v1/ton/price', params={'at':'2024-02-05','timezone':'Europe/Moscow','max_age_seconds':0})
    expected = client.get('/v1/ton/daily', params={'date':'2024-02-05','timezone':'Europe/Moscow'})
    assert result.status_code == 200
    assert result.json()['data'] == expected.json()['data']
    segment = result.json()['data']['segments'][0]
    assert [segment[key] for key in ('first','last','min','max')] == ['2.050000','2.11','2.050000','2.11']
    assert result.json()['data']['is_day_complete'] is True
    assert result.headers['x-request-id'] == result.json()['meta']['request_id']
    assert client.get('/v1/ton/price',params={'at':'2024-02-05'}).json()['data']['timezone'] == 'UTC'


@pytest.mark.parametrize('params,code', [
    ({'at':'2024-02-07'}, 'FUTURE_TIMESTAMP'),
    ({'at':'2024-02-05','timezone':'invalid'}, 'VALIDATION_ERROR'),
    ({'at':'2024-02-05','series':'unknown'}, 'SERIES_NOT_FOUND'),
    ({'at':'2024-02-05 12:00'}, 'VALIDATION_ERROR'),
])
def test_date_only_invalid_requests(client, params, code):
    response = client.get('/v1/ton/price', params=params)
    assert response.json()['code'] == code
    assert response.headers['content-type'] == 'application/problem+json'


def test_date_only_today_partial_and_empty_day(client, small_db):
    today = TestClient(create_app(small_db[1],clock=lambda:timestamp('2024-02-05T09:00:00Z')))
    data = today.get('/v1/ton/price',params={'at':'2024-02-05'}).json()['data']
    assert data['is_day_complete'] is False
    assert data['segments'][0]['points_count'] == 2
    assert data['segments'][0]['last'] == '2.06'
    empty = client.get('/v1/ton/price',params={'at':'2024-02-04'}).json()
    assert empty['data']['segments'] == []
    assert any(warning['code'] == 'NO_DATA' for warning in empty['meta']['warnings'])


def test_dst_day_is_23_hours(small_db):
    client = TestClient(create_app(small_db[1], clock=lambda: timestamp('2024-04-01T12:00:00Z')))
    data = client.get('/v1/ton/daily', params={'date':'2024-03-31','timezone':'Europe/Berlin'}).json()['data']
    assert timestamp(data['to']) - timestamp(data['from']) == 23*3600
    assert client.get('/v1/ton/price',params={'at':'2024-03-31','timezone':'Europe/Berlin'}).json()['data'] == data


def test_point_query_does_not_scan_between_requested_time_and_cutover(small_db, monkeypatch):
    from tonprices import app as app_module
    database = small_db[1]
    conn = connect(database, readonly=False)
    # Thousands of later observations make an accidentally broad seek observable
    # through SQLite's instruction budget, independently of machine speed.
    start = timestamp('2024-02-05T12:00:00Z')
    conn.executemany('INSERT INTO raw_messages(channel_id,message_id,posted_at,message_type,text,parse_status,raw_json_zlib) VALUES(123,?,?,\'message\',\'2$\',\'parsed\',X\'00\')', [(i,start+i) for i in range(10,10010)])
    conn.executemany("INSERT INTO prices(series_id,channel_id,message_id,observed_at,received_at,price,quote_currency,quote_basis,source) VALUES('telegram-usd',123,?,?,'2024-02-06T00:00:00Z','2','USD','channel_label','telegram')", [(i,start+i) for i in range(10,10010)])
    conn.execute("INSERT INTO metadata VALUES('calcmula_cutover_at',?)", (str(start+20000),))
    conn.commit(); conn.close()
    original = app_module.connect
    def budgeted(*args, **kwargs):
        connection = original(*args, **kwargs)
        connection.set_progress_handler(lambda: 1, 5000)
        return connection
    monkeypatch.setattr(app_module, 'connect', budgeted)
    test_client = TestClient(create_app(database,clock=lambda:start+30000))
    result = test_client.get('/v1/ton/price',params={'at':'2024-02-05T09:00:00Z'})
    assert result.status_code == 200
    assert result.json()['data']['price'] == '2.06'


def test_http_errors_and_coverage(client):
    assert client.get('/nothing').json()['code'] == 'ROUTE_NOT_FOUND'
    result = client.post('/v1/ton/price')
    assert result.status_code == 405 and result.headers.get('allow')
    assert result.json()['code'] == 'METHOD_NOT_ALLOWED'
    assert client.get('/v1/ton/price').json()['code'] == 'VALIDATION_ERROR'
    assert client.get('/v1/ton/coverage').json()['data']['segments'][0]['points_count'] == 4


def test_import_idempotency_and_no_silent_revision(small_db):
    source, database = small_db
    assert import_export(source, database)['already_imported']
    with connect(database) as conn:
        assert conn.execute('SELECT count(*) FROM prices').fetchone()[0] == 4
        assert conn.execute('SELECT count(*) FROM raw_messages').fetchone()[0] == 5
    source.write_text(source.read_text().replace('2.06$', '9.99$'))
    with pytest.raises(ValueError, match='another export'):
        import_export(source, database)


def test_price_parser_does_not_extract_numbers_from_prose():
    assert parse_price('Buy for 10$ now') is None
    assert parse_price('0$') is None
    assert parse_price('0.756269$') == '0.756269'


def test_real_archive_example():
    if not DEFAULT_DB.exists(): pytest.skip('Real archive not included in this environment')
    client = TestClient(create_app(DEFAULT_DB))
    body = client.get('/v1/ton/price', params={'at':'2024-02-05T12:00:00+03:00'}).json()
    assert body['data']['price'] == '2.05'
    assert body['data']['observed_at'] == '2024-02-05T08:58:16Z'
    assert body['data']['age_seconds'] == 104
    data = client.get('/v1/ton/daily', params={'date':'2024-02-05','timezone':'Europe/Moscow'}).json()['data']
    assert data['segments'][0]['points_count'] == 287
