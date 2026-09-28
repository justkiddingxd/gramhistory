// Presentation only: the historical USDT interval is treated as USD at 1:1.
// Original API currencies and stored observations are never changed.
export function comparePrices(left, right) {
  const parts = value => {
    if (typeof value !== 'string' || !/^\d+(?:\.\d+)?$/.test(value)) throw new Error('Invalid decimal price');
    const [whole, fraction = ''] = value.split('.');
    return [whole.replace(/^0+(?=\d)/, ''), fraction];
  };
  const [a, af] = parts(left), [b, bf] = parts(right);
  if (a.length !== b.length) return a.length < b.length ? -1 : 1;
  if (a !== b) return a < b ? -1 : 1;
  const width = Math.max(af.length, bf.length);
  const ap = af.padEnd(width, '0'), bp = bf.padEnd(width, '0');
  return ap === bp ? 0 : ap < bp ? -1 : 1;
}

export function displayCurrency(currency) {
  if (currency !== 'USD' && currency !== 'USDT') throw new Error('Unsupported quote currency');
  return { currency: 'USD', approximated: currency === 'USDT' };
}

export function summarizeDay(segments) {
  if (!segments.length) throw new Error('Empty daily summary');
  const time = value => {
    const parsed = Date.parse(value);
    if (!Number.isFinite(parsed)) throw new Error('Invalid observation time');
    return parsed;
  };
  const ordered = [...segments].sort((a, b) => time(a.first_at) - time(b.first_at));
  const last = ordered.reduce((a, b) => time(a.last_at) >= time(b.last_at) ? a : b);
  let min = ordered[0].min, max = ordered[0].max, count = 0, gap = 0, approximated = false;
  for (let index = 0; index < ordered.length; index++) {
    const segment = ordered[index];
    const currency = displayCurrency(segment.quote_currency);
    approximated = approximated || currency.approximated;
    if (!Number.isSafeInteger(segment.points_count) || segment.points_count < 1) throw new Error('Invalid observation count');
    count += segment.points_count;
    if (comparePrices(segment.min, min) < 0) min = segment.min;
    if (comparePrices(segment.max, max) > 0) max = segment.max;
    gap = Math.max(gap, segment.max_gap_seconds || 0);
    if (index) gap = Math.max(gap, (time(segment.first_at) - time(ordered[index - 1].last_at)) / 1000);
  }
  return { first: ordered[0].first, last: last.last, min, max, first_at: ordered[0].first_at,
    last_at: last.last_at, points_count: count, max_gap_seconds: gap, quote_currency: 'USD', approximated };
}
