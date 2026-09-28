import argparse
import collections
import json
import statistics
import time
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .db import connect, metadata


def iso(ts):
    return datetime.fromtimestamp(ts, UTC).isoformat().replace('+00:00', 'Z')


def audit(database, destination):
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=True)
    conn = connect(database, readonly=False)
    try:
        meta = metadata(conn)
        if meta.get('import_state') != 'complete':
            raise ValueError('Import is incomplete')
        integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
        fk_errors = conn.execute('PRAGMA foreign_key_check').fetchall()
        years, intervals = collections.Counter(), collections.Counter()
        gaps, previous, first, last, minimum, maximum = [], None, None, None, None, None
        total, edited, same_time = 0, 0, 0
        for row in conn.execute('SELECT observed_at,price,message_id,edited_at FROM prices WHERE series_id=? ORDER BY observed_at,message_id', ('telegram-usd',)):
            current = dict(row)
            total += 1
            edited += bool(current['edited_at'])
            years[iso(current['observed_at'])[:4]] += 1
            if first is None:
                first = current
            last = current
            value = Decimal(current['price'])
            if minimum is None or value < Decimal(minimum['price']): minimum = current
            if maximum is None or value > Decimal(maximum['price']): maximum = current
            if previous:
                diff = current['observed_at'] - previous['observed_at']
                intervals[diff] += 1
                same_time += diff == 0
                if diff > 900:
                    gaps.append({'from': iso(previous['observed_at']), 'to': iso(current['observed_at']), 'seconds': diff, 'previous_message_id': previous['message_id'], 'next_message_id': current['message_id']})
            previous = current
        raw_count, id_min, id_max = conn.execute('SELECT count(*),min(message_id),max(message_id) FROM raw_messages').fetchone()
        day_start = int(datetime(2024, 2, 5, tzinfo=timezone(timedelta(hours=3))).timestamp())
        day_rows = conn.execute('SELECT observed_at,price FROM prices WHERE series_id=? AND observed_at>=? AND observed_at<? ORDER BY observed_at,message_id', ('telegram-usd', day_start, day_start + 86400)).fetchall()
        target = day_start + 12*3600
        example = conn.execute('SELECT observed_at,price,message_id FROM prices WHERE series_id=? AND observed_at<=? ORDER BY observed_at DESC,message_id DESC LIMIT 1', ('telegram-usd', target)).fetchone()
        costs = []
        sql = 'SELECT price,observed_at FROM prices WHERE series_id=? AND observed_at<=? ORDER BY observed_at DESC,message_id DESC LIMIT 1'
        for index in range(1100):
            when = first['observed_at'] + (index * 7919 % (last['observed_at'] - first['observed_at']))
            start = time.perf_counter_ns()
            conn.execute(sql, ('telegram-usd', when)).fetchone()
            if index >= 100: costs.append((time.perf_counter_ns() - start)/1e6)
        costs.sort()
        plan = [list(row) for row in conn.execute('EXPLAIN QUERY PLAN ' + sql, ('telegram-usd', target))]
        def public(record):
            return {**record, 'observed_at': iso(record['observed_at']), 'edited_at': iso(record['edited_at']) if record.get('edited_at') else None}
        report = {
            'channel': meta['channel_name'], 'channel_id': int(meta['channel_id']), 'source_sha256': meta['source_sha256'],
            'source_size_bytes': int(meta['source_size_bytes']), 'raw_messages': raw_count, 'price_points': total,
            'non_price_messages': raw_count-total, 'first': public(first), 'last': public(last),
            'minimum': public(minimum), 'maximum': public(maximum), 'prices_by_year_utc': dict(years),
            'edited_price_messages': edited, 'same_timestamp_adjacent_points': same_time,
            'absent_ids_between_min_and_max': id_max-id_min+1-raw_count,
            'intervals_most_common_seconds': intervals.most_common(10),
            'gaps_over_15_minutes': len(gaps), 'largest_gaps': sorted(gaps, key=lambda item: item['seconds'], reverse=True)[:15],
            'sqlite_integrity_check': integrity, 'foreign_key_errors': len(fk_errors), 'lookup_query_plan': plan,
            'lookup_benchmark': {'samples': len(costs), 'median_ms': statistics.median(costs), 'p95_ms': costs[int(len(costs)*.95)-1], 'scope': 'Warm in-process SQLite lookup only; not HTTP latency or throughput.'},
            'example': {'requested_at': iso(target), 'requested_at_moscow': '2024-02-05T12:00:00+03:00', 'price': example['price'], 'quote_currency': 'USD', 'observed_at': iso(example['observed_at']), 'age_seconds': target-example['observed_at'], 'message_id': example['message_id']},
            'example_day': {'date': '2024-02-05', 'timezone': 'Europe/Moscow', 'count': len(day_rows), 'first': day_rows[0]['price'], 'last': day_rows[-1]['price'], 'min': str(min(Decimal(r['price']) for r in day_rows)), 'max': str(max(Decimal(r['price']) for r in day_rows))},
            'notes': ['USD inferred from dollar label; upstream quote denomination unknown.', 'Telegram export reflects current message text, including edits; original pre-edit values are unavailable.', 'Gaps identify time without posts; they do not establish that messages were deleted.', 'No interpolation or invented prices were added.']
        }
        (output / 'import-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
        (output / 'gaps.json').write_text(json.dumps(gaps, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
        conn.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', ('audit_summary', json.dumps(report)))
        conn.commit()
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        return report
    finally:
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.db, args.out), ensure_ascii=False, indent=2))
