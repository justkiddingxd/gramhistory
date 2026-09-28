export class PriceError extends Error {
  constructor(code) { super(code); this.code = code; }
}

export function createPriceClient(baseUrl, { fetchImpl = fetch, clock = Date.now, capacity = 512, timeoutMs = 3000 } = {}) {
  const cache = new Map(), pending = new Map();
  const base = new URL(baseUrl);
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password) throw new Error('Invalid price API base URL');
  return async function getPrice(query) {
    const url = new URL('/v1/ton/price', base);
    url.search = new URLSearchParams(query.params).toString();
    const key = url.href;
    const saved = cache.get(key);
    if (saved && saved.expires > clock()) return saved.body;
    if (pending.has(key)) return pending.get(key);
    if (pending.size >= 32) throw new PriceError('BUSY');
    const request = Promise.resolve().then(async () => {
      try {
        const response = await fetchImpl(url, { headers: { Accept: 'application/json', 'User-Agent': 'GramHistoryBot/1.0' }, signal: AbortSignal.timeout(timeoutMs), redirect: 'error' });
        const type = response.headers.get('content-type') || '';
        if (!type.includes('json')) throw new PriceError('UNAVAILABLE');
        const body = await response.json();
        if (!response.ok) throw new PriceError(body?.code || 'UNAVAILABLE');
        if (!body?.data || !body?.meta || (query.kind === 'daily' ? !Array.isArray(body.data.segments) : typeof body.data.price !== 'string')) throw new PriceError('UNAVAILABLE');
        const ttl = body.data.is_day_complete === false ? 5000 : 60000;
        cache.delete(key);
        cache.set(key, { body, expires: clock() + ttl });
        while (cache.size > capacity) cache.delete(cache.keys().next().value);
        return body;
      } catch (error) {
        if (error instanceof PriceError) throw error;
        throw new PriceError('UNAVAILABLE');
      } finally { pending.delete(key); }
    });
    pending.set(key, request);
    return request;
  };
}
