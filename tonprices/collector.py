"""One bounded public Calcmula request and an atomic, idempotent DB insert."""
import argparse
import json
import math
import re
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .db import connect, db_path, metadata, migrate_live

EXPRESSION = '1 ton in usd'
SERIES = 'calcmula-usd'
ENDPOINT = 'https://calcmula.app/api/calc'
INTERVAL = 300
MAX_BYTES = 65536


class ProviderError(Exception):
    pass


def decode_quote(body, headers, now):
    if len(body) > MAX_BYTES:
        raise ProviderError('Response exceeds size limit')
    if 'application/json' not in headers.get('Content-Type', '').lower():
        raise ProviderError('Provider returned non-JSON response')
    try:
        payload = json.loads(body, parse_float=Decimal, parse_int=Decimal)
        if not isinstance(payload, dict) or payload.get('ok') is not True or payload.get('expression') != EXPRESSION:
            raise ProviderError('Provider did not confirm the requested conversion')
        result = payload.get('result')
        if not isinstance(result, dict) or result.get('type') != 'value' or result.get('currency', '').lower() != 'usd':
            raise ProviderError('Expected a numeric USD result')
        currencies = payload.get('currencies')
        if not isinstance(currencies, list) or 'usd' not in currencies or not ({'ton', 'gram'} & set(currencies)):
            raise ProviderError('Unexpected source or quote currency')
        if payload.get('warnings') != []:
            raise ProviderError('Provider returned warnings')
        amount = result.get('amount')
        if not isinstance(amount, Decimal) or not amount.is_finite() or amount <= 0:
            raise ProviderError('Invalid positive price')
        if len(amount.as_tuple().digits) > 40 or not -30 <= amount.as_tuple().exponent <= 20:
            raise ProviderError('Price outside supported precision')
        age = headers.get('Age')
        if age is not None and (not re.fullmatch(r'\d+', age.strip()) or int(age) > 300):
            raise ProviderError('Stale or malformed HTTP cache age')
        if headers.get('Date'):
            served = parsedate_to_datetime(headers['Date']).timestamp()
            if served < now - 300 or served > now + 60:
                raise ProviderError('HTTP response date is stale or in the future')
        # Transport freshness is checkable; the underlying market timestamp is not supplied.
        return format(amount, 'f')
    except ProviderError:
        raise
    except (ValueError, TypeError, AttributeError, InvalidOperation, UnicodeError) as error:
        raise ProviderError('Malformed provider response') from error


def fetch_quote():
    request = Request(ENDPOINT + '?' + urlencode({'q': EXPRESSION}),
        headers={'Accept': 'application/json', 'Cache-Control': 'no-cache', 'User-Agent': 'TONPrices/0.5'})
    try:
        with urlopen(request, timeout=15) as response:
            if response.status != 200:
                raise ProviderError(f'Unexpected HTTP status {response.status}')
            if not response.url.startswith(ENDPOINT + '?'):
                raise ProviderError('Unexpected redirect')
            body = response.read(MAX_BYTES + 1)
            return body, dict(response.headers.items())
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise ProviderError(f'Provider request failed: {type(error).__name__}') from error


def collect_once(database=None, fetch=fetch_quote, clock=time.time):
    database = Path(database or db_path())
    migrate_live(database)
    owner = str(uuid.uuid4())
    started = int(clock())
    conn = connect(database, readonly=False)
    claimed = False
    try:
        conn.execute('BEGIN IMMEDIATE')
        existing = conn.execute('SELECT id,price,observed_at FROM live_prices WHERE series_id=? AND sample_bucket=?', (SERIES, started // INTERVAL * INTERVAL)).fetchone()
        if existing:
            conn.rollback()
            return {'status': 'already_recorded', **dict(existing)}
        state = conn.execute('SELECT * FROM collector_state WHERE name=?', ('calcmula',)).fetchone()
        if state and state['lease_until'] and state['lease_until'] > started:
            conn.rollback()
            return {'status': 'busy'}
        conn.execute('INSERT INTO collector_state(name,lease_owner,lease_until,last_attempt_at) VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET lease_owner=excluded.lease_owner,lease_until=excluded.lease_until,last_attempt_at=excluded.last_attempt_at', ('calcmula', owner, started + 120, started))
        conn.commit()
        claimed = True
        body, headers = fetch()
        # HTTP header lookup is case-insensitive, including headers from HTTP/2 clients.
        headers = {str(key).title(): str(value) for key, value in headers.items()}
        received = clock()
        if received < started or received - started > 90:
            raise ProviderError('Request clock or duration is invalid')
        price = decode_quote(body, headers, received)
        timestamp = int(received)
        bucket = timestamp // INTERVAL * INTERVAL
        received_at = datetime.fromtimestamp(received, UTC).isoformat().replace('+00:00', 'Z')
        conn.execute('BEGIN IMMEDIATE')
        state = conn.execute('SELECT lease_owner,lease_until FROM collector_state WHERE name=?', ('calcmula',)).fetchone()
        if not state or state['lease_owner'] != owner or state['lease_until'] < timestamp:
            raise ProviderError('Collector lease expired')
        inserted = conn.execute('INSERT OR IGNORE INTO live_prices(series_id,source,sample_bucket,observed_at,received_at,price,quote_currency,expression,response_json,http_date,provider_updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (SERIES, 'calcmula', bucket, timestamp, received_at, price, 'USD', EXPRESSION, body.decode('utf8'), headers.get('Date'), None)).rowcount
        first = conn.execute('SELECT min(observed_at) FROM live_prices').fetchone()[0]
        conn.execute('INSERT OR IGNORE INTO metadata VALUES(?,?)', ('calcmula_cutover_at', str(first)))
        first_usd = conn.execute('SELECT min(observed_at) FROM live_prices WHERE series_id=?', (SERIES,)).fetchone()[0]
        conn.execute('INSERT OR IGNORE INTO metadata VALUES(?,?)', ('calcmula_usd_cutover_at', str(first_usd)))
        conn.execute('UPDATE collector_state SET lease_owner=NULL,lease_until=NULL,last_success_at=?,last_error=NULL,consecutive_failures=0 WHERE name=? AND lease_owner=?', (timestamp, 'calcmula', owner))
        conn.commit()
        return {'status': 'inserted' if inserted else 'already_recorded', 'price': price, 'quote_currency': 'USD', 'source': 'calcmula', 'observed_at': timestamp, 'received_at': received_at, 'sample_bucket': bucket, 'timestamp_basis': 'retrieval_time'}
    except Exception as error:
        conn.rollback()
        if claimed:
            # Diagnostics contain only controlled messages, never a copied remote response.
            message = str(error) if isinstance(error, ProviderError) else type(error).__name__
            conn.execute('UPDATE collector_state SET lease_owner=NULL,lease_until=NULL,last_error=?,consecutive_failures=consecutive_failures+1 WHERE name=? AND lease_owner=?', (message[:300], 'calcmula', owner))
            conn.commit()
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description='Fetch TON/USD from Calcmula once, or run a standalone 5-minute worker.')
    parser.add_argument('--db', type=Path, default=db_path())
    parser.add_argument('--loop', action='store_true', help='Standalone deployment alternative; do not combine with another scheduler.')
    args = parser.parse_args()
    while True:
        try:
            print(json.dumps(collect_once(args.db)), flush=True)
        except Exception as error:
            print(json.dumps({'status': 'error', 'error': str(error) if isinstance(error, ProviderError) else type(error).__name__}), flush=True)
            if not args.loop:
                raise SystemExit(1)
        if not args.loop:
            return
        # UTC boundaries with a short offset; no stale historical values are manufactured after sleep.
        now = time.time()
        following = (math.floor(now / INTERVAL) + 1) * INTERVAL + 10
        while time.time() < following:
            time.sleep(min(30, max(0.01, following-time.time())))


if __name__ == '__main__':
    main()
