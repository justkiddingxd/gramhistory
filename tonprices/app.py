"""Read-only API over Telegram history and independently collected Calcmula snapshots."""
import base64
import hashlib
import json
import logging
import math
import re
import sqlite3
import time
import uuid
import weakref
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, date, datetime, time as day_time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from .db import ReadSnapshotCache, connect, db_path, metadata
from .download import ExportUnavailable, download_snapshot
from .exporter import export_directory

logger = logging.getLogger('tonprices')
TIMESTAMP = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
DateTimeText = Annotated[str, Field(json_schema_extra={'format': 'date-time'})]


class Source(BaseModel):
    provider: Literal['telegram', 'calcmula'] = 'telegram'
    symbol: str | None = None
    market: Literal['channel', 'conversion'] = 'channel'
    fallback: bool = False


class WarningItem(BaseModel):
    code: str
    message: str


class Meta(BaseModel):
    request_id: str
    api_version: Literal['1'] = '1'
    series: Literal['reference', 'telegram-usd', 'market-usdt', 'calcmula-usdt', 'calcmula-usd']
    policy_version: str = 'archive-v1'
    warnings: list[WarningItem]


class PageMeta(Meta):
    next_cursor: str | None
    limit: int


class Point(BaseModel):
    asset_id: Literal['toncoin'] = 'toncoin'
    price: str = Field(pattern=r'^(0|[1-9][0-9]*)(\.[0-9]+)?$')
    quote_currency: Literal['USD', 'USDT'] = 'USD'
    quote_basis: Literal['channel_label', 'provider_conversion'] = 'channel_label'
    kind: Literal['telegram_snapshot', 'api_snapshot'] = 'telegram_snapshot'
    timestamp_basis: Literal['message_time', 'retrieval_time'] = 'message_time'
    provider_updated_at: DateTimeText | None = None
    observed_at: DateTimeText
    received_at: DateTimeText
    interval_start: None = None
    interval_end: None = None
    source: Source
    revision: Literal[1] = 1


class Price(Point):
    requested_at: DateTimeText
    age_seconds: float
    max_age_seconds: int


class PriceResponse(BaseModel):
    data: Price
    meta: Meta


class HistoryResponse(BaseModel):
    data: list[Point]
    meta: PageMeta


class DailySegment(BaseModel):
    series: Literal['telegram-usd', 'calcmula-usdt', 'calcmula-usd']
    quote_currency: Literal['USD', 'USDT']
    kind: Literal['telegram_snapshot', 'api_snapshot']
    from_: DateTimeText = Field(alias='from')
    to: DateTimeText
    first: str
    last: str
    min: str
    max: str
    first_at: DateTimeText
    last_at: DateTimeText
    points_count: int
    expected_points: None = None
    max_gap_seconds: float
    coverage: Literal['unknown']
    providers: list[Literal['telegram', 'calcmula']]


class DailyData(BaseModel):
    kind: Literal['daily_summary'] = 'daily_summary'
    date: str
    timezone: str
    from_: DateTimeText = Field(alias='from')
    to: DateTimeText
    is_day_complete: bool
    segments: list[DailySegment]


class DailyResponse(BaseModel):
    data: DailyData
    meta: Meta


class CoverageSegment(BaseModel):
    series: Literal['telegram-usd', 'calcmula-usdt', 'calcmula-usd']
    quote_currency: Literal['USD', 'USDT']
    kind: Literal['telegram_snapshot', 'api_snapshot']
    first_at: DateTimeText | None
    last_at: DateTimeText | None
    points_count: int
    known_gap_count: int | None
    last_received_at: DateTimeText | None


class CoverageData(BaseModel):
    asset_id: Literal['toncoin']
    cutover_at: DateTimeText | None = None
    usd_cutover_at: DateTimeText | None = None
    collector: dict[str, str | int | None] | None = None
    segments: list[CoverageSegment]


class CoverageResponse(BaseModel):
    data: CoverageData
    meta: Meta


class SystemMeta(BaseModel):
    request_id: str
    api_version: Literal['1'] = '1'


class HealthResponse(BaseModel):
    data: dict[str, Literal['ok']]
    meta: SystemMeta


class Problem(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    request_id: str
    errors: list[dict[str, str]] | None = None


class ApiError(Exception):
    def __init__(self, status, code, detail, errors=None, headers=None):
        self.status, self.code, self.detail = status, code, detail
        self.errors, self.headers = errors, headers or {}


def utc(seconds):
    return datetime.fromtimestamp(seconds, UTC).isoformat().replace('+00:00', 'Z')


def parse_timestamp(value, field):
    try:
        if not TIMESTAMP.fullmatch(value): raise ValueError()
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.timestamp()
    except (ValueError, OverflowError):
        raise ApiError(422, 'VALIDATION_ERROR', f'{field} must be RFC 3339 with seconds and timezone.')


def requested_series(value):
    if value not in ('reference', 'telegram-usd', 'market-usdt', 'calcmula-usdt', 'calcmula-usd'):
        raise ApiError(404, 'SERIES_NOT_FOUND', 'Unknown price series.')
    return value


def selection(connection, series, when):
    requested_series(series)
    if series != 'reference':
        return 'series_id=?', [series]
    values = metadata(connection)
    usd_cutoff = values.get('calcmula_usd_cutover_at')
    if usd_cutoff is not None and when >= int(usd_cutoff):
        return 'series_id=?', ['calcmula-usd']
    cutoff = values.get('calcmula_cutover_at')
    if cutoff is None:
        return 'series_id=?', ['telegram-usd']
    cutoff = int(cutoff)
    return 'series_id=?', ['telegram-usd' if when < cutoff else 'calcmula-usdt']


def point(row):
    row = dict(row)
    live = row['source'] == 'calcmula'
    source = Source(provider=row['source'], symbol='GRAM/' + row['quote_currency'] if live else None, market='conversion' if live else 'channel')
    return Point(price=row['price'], quote_currency=row['quote_currency'], quote_basis='provider_conversion' if live else 'channel_label', kind='api_snapshot' if live else 'telegram_snapshot',
        timestamp_basis='retrieval_time' if live else 'message_time', provider_updated_at=utc(row['provider_updated_at']) if row.get('provider_updated_at') is not None else None,
        observed_at=utc(row['observed_at']), received_at=row['received_at'], source=source).model_dump()


def source_ranges(series, cutoff, start=None, end=None, usd_cutoff=None):
    """Resolve each source to one exact half-open index range."""
    requested_series(series)
    candidates = ['telegram-usd', 'calcmula-usdt'] if series == 'reference' and cutoff else ['telegram-usd'] if series == 'reference' else [series]
    if series == 'reference' and usd_cutoff is not None:
        candidates.append('calcmula-usd')
    for selected in candidates:
        if selected == 'market-usdt':
            continue
        lower, upper = start, end
        if series == 'reference' and cutoff:
            if selected == 'telegram-usd': upper = min(upper, cutoff) if upper is not None else cutoff
            else: lower = max(lower, cutoff) if lower is not None else cutoff
        if series == 'reference' and usd_cutoff is not None:
            if selected == 'calcmula-usd': lower = max(lower, usd_cutoff) if lower is not None else usd_cutoff
            else: upper = min(upper, usd_cutoff) if upper is not None else usd_cutoff
        if lower is not None and upper is not None and lower >= upper:
            continue
        live = selected in ('calcmula-usdt', 'calcmula-usd')
        yield selected, 'live_prices' if live else 'prices', live, lower, upper


def range_rows(connection, series, cutoff, start, end, limit=None, cursor=None, usd_cutoff=None):
    rows = []
    for selected, table, live, lower, upper in source_ranges(series, cutoff, start, end, usd_cutoff):
        tie = 'id' if live else 'message_id'
        if cursor:
            lower = max(lower, cursor[0])
        clause = f' AND (observed_at,{tie})>(?,?)' if cursor else ''
        values = [selected, lower, upper, *(cursor or ())]
        fields = "*,id AS message_id,'api_snapshot' AS kind" if live else "*,'telegram_snapshot' AS kind"
        sql = f'SELECT {fields} FROM {table} WHERE series_id=? AND observed_at>=? AND observed_at<?{clause} ORDER BY observed_at,{tie}'
        if limit is not None:
            sql += ' LIMIT ?'
            values.append(limit - len(rows))
        rows.extend(connection.execute(sql, values).fetchall())
        if limit is not None and len(rows) >= limit:
            break
    return rows


def response_meta(request, series, warnings=None, sources=None):
    cutoff = getattr(request.state, 'cutover_at', None)
    usd_cutoff = getattr(request.state, 'usd_cutover_at', None)
    if sources is None:
        sources = {'calcmula'} if series in ('calcmula-usdt', 'calcmula-usd') else {'telegram'}
    notices = []
    if not cutoff:
        notices.append({'code': 'ARCHIVE_ONLY', 'message': 'No Calcmula observations have been recorded yet.'})
    if series == 'reference' and cutoff:
        notices.append({'code': 'SOURCE_TRANSITION', 'message': 'Reference selects Telegram before cutover, legacy Calcmula USDT until usd_cutover_at, then Calcmula USD. Check quote_currency; no currency conversion is applied.'})
    if 'telegram' in sources:
        notices.extend([
            {'code': 'USD_LABEL_UNVERIFIED', 'message': 'USD is inferred from the dollar label; the original quote source is unknown.'},
            {'code': 'EXPORTED_MESSAGE_STATE', 'message': 'Values reflect exported message text; original pre-edit values are unavailable.'}])
    if 'calcmula' in sources:
        notices.append({'code': 'PROVIDER_TIMESTAMP_UNAVAILABLE', 'message': 'Calcmula does not supply the market-rate update time. observed_at is our retrieval time.'})
    return {'request_id': request.state.request_id, 'api_version': '1', 'series': series, 'policy_version': 'reference-calcmula-usd-v2' if usd_cutoff is not None else 'reference-calcmula-v1' if cutoff else 'archive-v1', 'warnings': notices + (warnings or [])}


def cursor_key(value, query_hash):
    try:
        decoded = json.loads(base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)))
        if decoded['q'] != query_hash or type(decoded['t']) is not int or type(decoded['id']) is not int:
            raise ValueError()
        if not 0 <= decoded['t'] < 4102444800 or not 0 < decoded['id'] < 2**63:
            raise ValueError()
        return decoded['t'], decoded['id']
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise ApiError(422, 'VALIDATION_ERROR', 'Invalid cursor or cursor does not match query filters.')


def create_app(database=None, clock=time.time, exports=None):
    database = Path(database) if database else db_path()
    exports = Path(exports) if exports else export_directory(database)
    coverage_cache = ReadSnapshotCache(database)

    @asynccontextmanager
    async def lifespan(application):
        yield
        coverage_cache.close()

    application = FastAPI(title='TON Prices API — archive and Calcmula', version='0.6.0', docs_url='/swagger', lifespan=lifespan,
        description='Read-only API. The collector requests TON/USD every 5 minutes. Reference selects Telegram USD before cutover_at, legacy Calcmula USDT until usd_cutover_at, then Calcmula USD. Original currencies are preserved. Snapshots are not exchange candle closes; the provider market timestamp is unavailable. No synchronous upstream requests are made by this API.')
    weakref.finalize(application, coverage_cache.close)
    common_errors = {str(status): {'description': description, 'content': {'application/problem+json': {'schema': Problem.model_json_schema()}}} for status, description in [(404, 'No price, data gap or unknown series'), (422, 'Invalid request'), (503, 'Database unavailable or latest price stale'), (500, 'Internal error')]}

    docs_directory = Path(__file__).resolve().parent / 'static_docs'
    application.mount('/docs-assets', StaticFiles(directory=docs_directory), name='docs-assets')

    @application.get('/', include_in_schema=False)
    def homepage():
        return FileResponse(docs_directory / 'home.html', media_type='text/html')

    @application.get('/docs', include_in_schema=False)
    def documentation():
        return FileResponse(docs_directory / 'index.html', media_type='text/html')

    @application.get('/skill.md', include_in_schema=False)
    def agent_skill():
        return FileResponse(Path(__file__).resolve().parent / 'skills' / 'gram-prices' / 'SKILL.md',
            media_type='text/markdown; charset=utf-8',
            headers={'Content-Disposition': 'inline; filename="skill.md"'})

    @contextmanager
    def database_connection(request=None):
        connection = connect(database)
        try:
            validate_database(connection, request)
            yield connection
        finally:
            connection.close()

    def validate_database(connection, request=None):
        values = metadata(connection)
        if values.get('import_state') != 'complete':
            raise ApiError(503, 'DATABASE_UNAVAILABLE', 'Archive import has not completed.')
        if request is not None:
            cutoff = values.get('calcmula_cutover_at')
            request.state.cutover_at = int(cutoff) if cutoff else None
            usd_cutoff = values.get('calcmula_usd_cutover_at')
            request.state.usd_cutover_at = int(usd_cutoff) if usd_cutoff else None
        return values

    @application.middleware('http')
    async def correlation(request, call_next):
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        response.headers.setdefault('Cache-Control', 'no-store')
        return response

    def error_response(request, error):
        request_id = getattr(request.state, 'request_id', str(uuid.uuid4()))
        content = Problem(type='/problems/' + error.code.lower().replace('_', '-'), title=error.code.replace('_', ' ').title(), status=error.status,
            detail=error.detail, instance=request.url.path, code=error.code, request_id=request_id, errors=error.errors).model_dump(exclude_none=True)
        return JSONResponse(content, status_code=error.status, media_type='application/problem+json', headers={'X-Request-ID': request_id, 'Cache-Control': 'no-store', **error.headers})

    @application.exception_handler(ApiError)
    async def api_error(request, error):
        return error_response(request, error)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        details = [{'field': '.'.join(str(part) for part in item['loc']), 'reason': item['msg']} for item in error.errors()]
        return error_response(request, ApiError(422, 'VALIDATION_ERROR', 'Request parameters failed validation.', errors=details))

    @application.exception_handler(HTTPException)
    async def http_error(request, error):
        code = 'METHOD_NOT_ALLOWED' if error.status_code == 405 else 'ROUTE_NOT_FOUND' if error.status_code == 404 else 'HTTP_ERROR'
        return error_response(request, ApiError(error.status_code, code, 'HTTP request could not be handled.', headers=error.headers))

    @application.exception_handler(sqlite3.Error)
    async def database_error(request, error):
        logger.error('Database unavailable: %s', type(error).__name__)
        return error_response(request, ApiError(503, 'DATABASE_UNAVAILABLE', 'Local price database is unavailable.'))

    @application.exception_handler(Exception)
    async def unexpected_error(request, error):
        logger.exception('Unhandled API error')
        return error_response(request, ApiError(500, 'INTERNAL_ERROR', 'Unexpected server error.'))

    def lookup(request, when, series, max_age, latest=False):
        requested_series(series)
        with database_connection(request) as connection:
            where, values = selection(connection, series, when)
            # Point lookups have one selected source. Query its time index directly;
            # sorting the UNION view would materialize every earlier observation.
            table, tie_breaker = ('live_prices', 'id') if values[0] in ('calcmula-usdt', 'calcmula-usd') else ('prices', 'message_id')
            # The timestamp already determines the reference source. Two upper
            # bounds let SQLite seek to the later cutoff and scan years backwards.
            # A single bound seeks directly to the requested observation.
            row = connection.execute('SELECT * FROM ' + table + ' WHERE series_id=? AND observed_at<=? ORDER BY observed_at DESC,' + tie_breaker + ' DESC LIMIT 1', [values[0], when]).fetchone()
        if row is None:
            raise ApiError(404, 'PRICE_NOT_FOUND', 'No price exists at or before the requested time in this series.')
        age = round(when - row['observed_at'], 6)
        if age > max_age:
            raise ApiError(503 if latest else 404, 'PRICE_STALE' if latest else 'DATA_GAP', 'Last available price exceeds max_age_seconds.')
        return {'data': {**point(row), 'requested_at': utc(when), 'age_seconds': age, 'max_age_seconds': max_age}, 'meta': response_meta(request, series, sources={row['source']})}

    @application.head('/v1/ton/export', include_in_schema=False)
    @application.get('/v1/ton/export', response_class=FileResponse,
        summary='Download the complete database as a compressed SQLite snapshot',
        description='All series and original public-channel messages. A separate worker prepares a consistent snapshot every 5 minutes. Gzip file, not a JSON envelope. HEAD returns download metadata; If-None-Match supports 304. Snapshots older than 15 minutes return 503.',
        responses={**common_errors, 200: {'description': 'Complete SQLite database compressed with gzip', 'content': {'application/gzip': {'schema': {'type': 'string', 'format': 'binary'}}}}, 304: {'description': 'Snapshot has not changed'}})
    def export_database(request: Request):
        try:
            return download_snapshot(exports, request, clock())
        except ExportUnavailable as error:
            raise ApiError(503, 'EXPORT_STALE' if error.stale else 'EXPORT_UNAVAILABLE',
                           'The prepared snapshot is older than 15 minutes.' if error.stale else 'The database snapshot is not ready. Retry shortly.',
                           headers={'Retry-After': '60'}) from None

    @application.get('/v1/ton/price/latest', response_model=PriceResponse, responses=common_errors)
    def latest(request: Request, series: str = 'reference', max_age_seconds: Annotated[int, Query(ge=0, le=86400)] = 900):
        return lookup(request, clock(), series, max_age_seconds, latest=True)

    @application.get('/v1/ton/price', response_model=PriceResponse | DailyResponse, responses=common_errors,
        summary='Price at a timestamp or daily summary for a calendar date')
    def at_time(request: Request,
        at: Annotated[str, Query(description='RFC 3339 timestamp returns one price; YYYY-MM-DD returns the daily summary.', examples=['2024-02-05', '2024-02-05T09:00:00Z'])],
        series: str = 'reference', max_age_seconds: Annotated[int, Query(ge=0, le=86400, description='Maximum age for timestamp lookups only; not applied to daily summaries.')] = 900,
        timezone: Annotated[str, Query(description='IANA timezone for date-only summaries; timestamps use their own offset.')] = 'UTC'):
        if DATE.fullmatch(at):
            return daily(request, at, timezone, series)
        when = parse_timestamp(at, 'at')
        if when > clock(): raise ApiError(422, 'FUTURE_TIMESTAMP', 'Future price queries are not supported.')
        return lookup(request, when, series, max_age_seconds)

    @application.get('/v1/ton/history', response_model=HistoryResponse, responses=common_errors)
    def history(request: Request, from_: Annotated[str, Query(alias='from')], to: str, series: str = 'reference',
        limit: Annotated[int, Query(ge=1, le=1000)] = 500, cursor: Annotated[str | None, Query(max_length=2048)] = None):
        requested_series(series)
        start, end = parse_timestamp(from_, 'from'), parse_timestamp(to, 'to')
        if end <= start or end - start > 366*86400 or end > clock():
            raise ApiError(422, 'VALIDATION_ERROR', 'Range must be positive, at most 366 days, and end no later than now.')
        query_hash = hashlib.sha256(json.dumps([series, start, end, limit]).encode()).hexdigest()[:24]
        position = cursor_key(cursor, query_hash) if cursor else None
        with database_connection(request) as connection:
            rows = range_rows(connection, series, request.state.cutover_at, start, end, limit+1, position, request.state.usd_cutover_at)
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            next_cursor = base64.urlsafe_b64encode(json.dumps({'q': query_hash, 't': rows[-1]['observed_at'], 'id': rows[-1]['message_id']}, separators=(',', ':')).encode()).decode().rstrip('=')
        return {'data': [point(row) for row in rows], 'meta': {**response_meta(request, series, sources={row['source'] for row in rows}), 'next_cursor': next_cursor, 'limit': limit}}

    @application.get('/v1/ton/daily', response_model=DailyResponse, responses=common_errors)
    def daily(request: Request, date_: Annotated[str, Query(alias='date')], timezone: str = 'UTC', series: str = 'reference'):
        requested_series(series)
        try:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date_): raise ValueError()
            selected_day, zone = date.fromisoformat(date_), ZoneInfo(timezone)
            start = datetime.combine(selected_day, day_time(), zone).timestamp()
            end = datetime.combine(selected_day + timedelta(days=1), day_time(), zone).timestamp()
        except (ValueError, ZoneInfoNotFoundError, OverflowError):
            raise ApiError(422, 'VALIDATION_ERROR', 'Invalid date or IANA timezone.')
        now = clock()
        if selected_day > datetime.fromtimestamp(now, zone).date():
            raise ApiError(422, 'FUTURE_TIMESTAMP', 'Future daily queries are not supported.')
        with database_connection(request) as connection:
            rows = range_rows(connection, series, request.state.cutover_at, start, min(end, math.floor(now)+1), usd_cutoff=request.state.usd_cutover_at)
        bounds = {selected: (lower, upper) for selected, _, _, lower, upper in source_ranges(series, request.state.cutover_at, start, end, request.state.usd_cutover_at)}
        segments = []
        for group_series in dict.fromkeys(row['series_id'] for row in rows):
            group = [row for row in rows if row['series_id'] == group_series]
            segment_start, segment_end = bounds[group_series]
            gaps = [group[0]['observed_at']-segment_start, min(segment_end,now)-group[-1]['observed_at']]
            gaps.extend(right['observed_at']-left['observed_at'] for left,right in zip(group,group[1:]))
            segments.append({'series': group_series, 'quote_currency': group[0]['quote_currency'], 'kind': group[0]['kind'], 'from': utc(segment_start), 'to': utc(segment_end),
                'first': group[0]['price'], 'last': group[-1]['price'], 'min': min(group, key=lambda row: Decimal(row['price']))['price'], 'max': max(group, key=lambda row: Decimal(row['price']))['price'],
                'first_at': utc(group[0]['observed_at']), 'last_at': utc(group[-1]['observed_at']), 'points_count': len(group), 'expected_points': None, 'max_gap_seconds': max(gaps), 'coverage': 'unknown', 'providers': [group[0]['source']]})
        warnings = [] if rows else [{'code': 'NO_DATA', 'message': 'No observations in this day.'}]
        return {'data': {'date': date_, 'timezone': timezone, 'from': utc(start), 'to': utc(end), 'is_day_complete': now >= end, 'segments': segments}, 'meta': response_meta(request, series, warnings, sources={row['source'] for row in rows})}

    @application.get('/v1/ton/coverage', response_model=CoverageResponse, responses=common_errors)
    def coverage(request: Request, series: str = 'reference'):
        requested_series(series)
        with coverage_cache.snapshot() as (connection, cached):
            values = validate_database(connection, request)
            if series not in cached:
                stats = []
                for selected, table, live, lower, upper in source_ranges(series, request.state.cutover_at, usd_cutoff=request.state.usd_cutover_at):
                    conditions, args = ['series_id=?'], [selected]
                    if lower is not None: conditions.append('observed_at>=?'); args.append(lower)
                    if upper is not None: conditions.append('observed_at<?'); args.append(upper)
                    group = dict(connection.execute(f'SELECT count(*) AS n,min(observed_at) AS first,max(observed_at) AS last,max(received_at) AS received FROM {table} WHERE ' + ' AND '.join(conditions), args).fetchone())
                    if group['n']:
                        stats.append({**group, 'series_id': selected, 'quote_currency': 'USDT' if selected == 'calcmula-usdt' else 'USD', 'kind': 'api_snapshot' if live else 'telegram_snapshot', 'source': 'calcmula' if live else 'telegram'})
                cached[series] = stats
            stats = cached[series]
            audit = json.loads(values.get('audit_summary', '{}'))
            state = connection.execute('SELECT last_attempt_at,last_success_at,last_error,consecutive_failures FROM collector_state WHERE name=?', ('calcmula',)).fetchone()
        segments = []
        for group in stats:
            segments.append({'series': group['series_id'], 'quote_currency': group['quote_currency'], 'kind': group['kind'], 'first_at': utc(group['first']), 'last_at': utc(group['last']),
                'points_count': group['n'], 'known_gap_count': audit.get('gaps_over_15_minutes') if group['source'] == 'telegram' else None, 'last_received_at': group['received']})
        collector = {**dict(state), 'interval_seconds': 300, 'source': 'calcmula'} if state else None
        return {'data': {'asset_id': 'toncoin', 'cutover_at': utc(request.state.cutover_at) if request.state.cutover_at else None, 'usd_cutover_at': utc(request.state.usd_cutover_at) if request.state.usd_cutover_at is not None else None, 'segments': segments, 'collector': collector}, 'meta': response_meta(request, series, sources={group['source'] for group in stats})}

    @application.get('/health/live', response_model=HealthResponse)
    def live(request: Request):
        return {'data': {'status': 'ok'}, 'meta': {'request_id': request.state.request_id, 'api_version': '1'}}

    @application.get('/health/ready', response_model=HealthResponse, responses=common_errors)
    def ready(request: Request):
        with database_connection() as connection:
            connection.execute('SELECT observed_at FROM prices LIMIT 1').fetchone()
        return live(request)

    return application


app = create_app()
