import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DateTime } from 'luxon';
import { parseQuery, QueryError } from '../src/query.js';
import { createPriceClient, PriceError } from '../src/prices.js';
import { createInlineHandler, createChosenHandler } from '../src/inline.js';
import { priceResult, helpResult, noticeResult } from '../src/render.js';
import { comparePrices, summarizeDay } from '../src/summary.js';

const now = DateTime.fromISO('2026-09-28T12:00:00Z');
const parse = input => parseQuery(input, { now });
const segment = { series: 'telegram-usd', quote_currency: 'USD', providers: ['telegram'], first: '2.050000', last: '2.06', min: '2.04', max: '2.07000000000000001', first_at: '2022-04-23T21:01:00Z', last_at: '2022-04-24T20:59:00Z', points_count: 287, max_gap_seconds: 400 };
const daily = { data: { kind: 'daily_summary', date: '2022-04-24', segments: [segment], is_day_complete: true }, meta: { warnings: [] } };
const response = (body = daily, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

test('short date selects daily API and Moscow without language-based guesses', () => {
  const query = parse('24.04.22');
  assert.equal(query.kind, 'daily');
  assert.deepEqual(query.params, { at: '2022-04-24', timezone: 'Europe/Moscow' });
  assert.equal(query.defaultZone, true);
  assert.equal(parse('24.04.2022').params.at, '2022-04-24');
});
for (const [input, expected] of [
  ['24.04.22 15:30', '2022-04-24T12:30:00Z'],
  ['24.04.22 15:30:45 МСК', '2022-04-24T12:30:45Z'],
  ['24.04.2022 15:30 UTC+5', '2022-04-24T10:30:00Z'],
  ['24.04.22 00:30 UTC+05:30', '2022-04-23T19:00:00Z'],
  ['2022-04-24T15:30:00+03:00', '2022-04-24T12:30:00Z'],
  ['2022-04-24T15:30:00Z', '2022-04-24T15:30:00Z'],
  ['24.04.22 15:30 Europe/Berlin', '2022-04-24T13:30:00Z'],
  ['24.01.22 15:30 Europe/Berlin', '2022-01-24T14:30:00Z'],
]) test(`timestamp conversion: ${input}`, () => assert.equal(parse(input).params.at, expected));

test('daily explicit UTC and offsets map to API-supported IANA zones', () => {
  assert.deepEqual(parse('24.04.22 UTC+5').params, { at: '2022-04-24', timezone: 'Etc/GMT-5' });
  assert.equal(parse('24.04.22 UTC').params.timezone, 'UTC');
  assert.equal(parse('24.04.22 Asia/Kolkata').params.timezone, 'Asia/Kolkata');
  assert.equal(parse('24.04.22 UTC-5').params.timezone, 'Etc/GMT+5');
});
for (const input of ['31.04.22', '29.02.23', '24.13.22', '24.04.22 24:00', '24.04.22 12:60', '24.04.22 12:00:60', '24.04.22 12:00 UTC+15', '24.04.22 12:00 Bad/Zone', '29.09.26', '28.09.26 15:00:01 МСК', '24.04.22 UTC+05:30', 'hello <b>']) {
  test(`invalid query gives actionable notice: ${input}`, () => assert.throws(() => parse(input), QueryError));
}
test('DST gaps and ambiguous exact times require an explicit offset', () => {
  assert.throws(() => parse('31.03.24 02:30 Europe/Berlin'), /перевода часов/);
  assert.throws(() => parse('27.10.24 02:30 Europe/Berlin'), /неоднозначно/);
  assert.equal(parse('27.10.24 02:30 UTC+2').params.at, '2024-10-27T00:30:00Z');
  assert.equal(parse('31.03.24 Europe/Berlin').params.at, '2024-03-31');
});
test('leap day, today and empty query', () => {
  assert.equal(parse('29.02.24').params.at, '2024-02-29');
  assert.equal(parse('28.09.26').kind, 'daily');
  assert.equal(parse('').kind, 'help');
});
test('native Rich Message blocks include custom emojis, one table, exact decimals and source', () => {
  const result = priceResult(parse('24.04.22'), daily);
  assert.equal(result.type, 'article');
  const rich = result.input_message_content.rich_message;
  assert.equal(rich.html, undefined);
  assert.deepEqual(rich.blocks[0], { type: 'heading', size: 2, text: [{ type: 'custom_emoji', custom_emoji_id: '6006074913742396956', alternative_text: '💎' }, ' GRAM · 24.04.2022'] });
  assert.equal(rich.blocks.filter(block => block.type === 'table').length, 1);
  const text = JSON.stringify(rich);
  assert.match(text, /2,07000000000000001/);
  assert.match(text, /2,050000/);
  assert.match(text, /МСК/);
  assert.match(text, /@tonprices/);
  const emojis = [];
  const walk = value => {
    if (!value || typeof value !== 'object') return;
    if (value.type === 'custom_emoji') emojis.push(value.custom_emoji_id);
    Object.values(value).forEach(walk);
  };
  walk(rich);
  for (const id of ['6006074913742396956', '5960551395730919906', '5798535677318533269', '5900006938271288826', '5875078273775439450', '5875008416132370818', '5874960879434338403', '5884343982816759327', '5886666250158870040']) assert.ok(emojis.includes(id), id);
  assert.equal(emojis.filter(id => id === '5798535677318533269').length, 2);
  assert.equal(emojis.filter(id => id === '5900006938271288826').length, 2);
  assert.ok(!('message_text' in result.input_message_content));
  assert.equal(result.input_message_content.rich_message.skip_entity_detection, true);
  assert.ok(Buffer.byteLength(result.id) <= 64);
});
test('mixed currencies give a single USD table with an explicit 1:1 footer', () => {
  const body = { ...daily, data: { ...daily.data, is_day_complete: false, segments: [segment, { ...segment, series: 'calcmula-usdt', quote_currency: 'USDT', providers: ['calcmula'], max_gap_seconds: 1200 }] } };
  const before = JSON.stringify(body);
  const rich = priceResult(parse('24.04.22'), body).input_message_content.rich_message;
  assert.equal(rich.blocks.filter(block => block.type === 'table').length, 1);
  const text = JSON.stringify(rich);
  assert.match(text, /сводка неполная/);
  assert.match(text, /Пропуски >15 мин/);
  assert.match(text, /2,050000 USD/);
  assert.doesNotMatch(text, /2,050000 USDT/);
  assert.match(rich.blocks.at(-1).text, /USDT ≈ USD \(1:1\)/);
  assert.equal(rich.blocks.find(block => block.type === 'table').cells.at(-1)[1].text.text, '574');
  assert.equal(JSON.stringify(body), before, 'the API response must not be mutated');
});

test('merged summary chooses chronological endpoints and precise extrema across three segments', () => {
  const a = { ...segment, first: '1.56', last: '1.60', min: '1.55', max: '1.63', first_at: '2026-09-26T21:01:01Z', last_at: '2026-09-27T05:43:43Z', points_count: 96 };
  const b = { ...segment, quote_currency: 'USDT', first: '1.590396008606143', last: '1.6203467542054002', min: '1.5802591625026505', max: '1.7104378720952564', first_at: '2026-09-27T06:19:06Z', last_at: '2026-09-27T20:55:10Z', points_count: 175 };
  const c = { ...segment, first: '1.71043787209525641', last: '1.60', min: '1.60', max: '1.71043787209525641', first_at: '2026-09-27T21:00:00Z', last_at: '2026-09-27T21:55:00Z', points_count: 11 };
  const two = summarizeDay([b, a]);
  assert.equal(two.first, '1.56');
  assert.equal(two.last, '1.6203467542054002');
  assert.equal(two.min, '1.55');
  assert.equal(two.max, '1.7104378720952564');
  assert.equal(two.points_count, 271);
  assert.equal(two.max_gap_seconds, 2123);
  const three = summarizeDay([b, c, a]);
  assert.equal(three.max, '1.71043787209525641');
  assert.equal(three.last, '1.60');
  assert.equal(three.points_count, 282);
  assert.equal(comparePrices('9.999999999999999999', '10.0'), -1);
  assert.equal(comparePrices('02.050000', '2.05'), 0);
  assert.throws(() => summarizeDay([b, { ...c, quote_currency: 'EUR' }]), /Unsupported/);
});
test('exact time shows actual observation, amount and currency', () => {
  const body = { data: { price: '1.234567890123456789', quote_currency: 'USD', requested_at: '2022-04-24T12:30:00Z', observed_at: '2022-04-24T12:28:16Z', age_seconds: 104, source: { provider: 'calcmula' } }, meta: { warnings: [] } };
  const text = JSON.stringify(priceResult(parse('24.04.22 15:30'), body).input_message_content.rich_message);
  assert.match(text, /15:30:00/);
  assert.match(text, /15:28:16/);
  assert.match(text, /1,234567890123456789 USD/);
  assert.match(text, /104 с/);
  assert.doesNotMatch(text, /USDT ≈ USD/);
  const usdt = priceResult(parse('24.04.22 15:30'), { ...body, data: { ...body.data, quote_currency: 'USDT' } });
  assert.match(usdt.title, / USD$/);
  assert.match(JSON.stringify(usdt.input_message_content.rich_message), /1,234567890123456789 USD/);
  assert.match(JSON.stringify(usdt.input_message_content.rich_message.blocks.at(-1)), /USDT ≈ USD \(1:1\)/);
});
test('empty history is not rendered as zero; rich HTML is escaped', () => {
  assert.match(priceResult(parse('24.04.22'), { ...daily, data: { ...daily.data, segments: [] } }).description, /не нулевая/);
  assert.match(noticeResult('<script>', '<b>oops</b>').input_message_content.rich_message.html, /&lt;script&gt;/);
  assert.ok(helpResult().input_message_content.rich_message.html.includes('@gramhistorybot'));
});
test('API client deduplicates concurrent calls, uses encoded local request and exact values', async () => {
  let calls = 0;
  const client = createPriceClient('http://api:8087', { fetchImpl: async url => { calls++; assert.equal(new URL(url).searchParams.get('timezone'), 'Europe/Moscow'); return response(); } });
  const query = parse('24.04.22');
  const [a, b] = await Promise.all([client(query), client(query)]);
  assert.equal(calls, 1);
  assert.equal(a.data.segments[0].first, '2.050000');
  assert.equal(a, b);
  await client(query);
  assert.equal(calls, 1);
});
test('API client does not cache failures and refreshes unfinished days', async () => {
  let calls = 0, clock = 0;
  const client = createPriceClient('http://api:8087', { clock: () => clock, fetchImpl: () => { calls++; if (calls === 1) throw new Error('connection'); return response({ ...daily, data: { ...daily.data, is_day_complete: false } }); } });
  await assert.rejects(client(parse('24.04.22')), PriceError);
  await client(parse('24.04.22'));
  clock = 5001;
  await client(parse('24.04.22'));
  assert.equal(calls, 3);
});
test('HTTP API errors are mapped and never become a zero price', async () => {
  const client = createPriceClient('http://api:8087', { fetchImpl: async () => response({ code: 'DATA_GAP' }, 404) });
  await assert.rejects(client(parse('24.04.22 15:30')), error => error.code === 'DATA_GAP');
});
test('inline listing immediately returns Loading with an editable keyboard and no price request', async () => {
  const replies = [];
  const handler = createInlineHandler({ getPrice: () => assert.fail('Prices must only load after selection'), answer: async params => replies.push(params) });
  await handler({ id: 'test', query: '24.04.22', offset: '', from: { language_code: 'en' } });
  assert.equal(replies[0].inline_query_id, 'test');
  assert.equal(replies[0].cache_time, 0);
  assert.equal(replies[0].is_personal, true);
  assert.equal(replies[0].results[0].input_message_content.message_text, 'Loading...');
  assert.match(replies[0].results[0].description, /МСК/);
  assert.ok(replies[0].results[0].reply_markup.inline_keyboard[0].length);
  assert.ok(Buffer.byteLength(replies[0].results[0].id) <= 64);
  await handler({ id: 'next', query: '24.04.22', offset: 'next' });
  assert.deepEqual(replies[1].results, []);
  await handler({ id: 'invalid', query: '31.04.22' });
  assert.match(replies[2].results[0].description, /нет в календаре/);
  await handler({ id: 'help', query: '' });
  assert.match(replies[3].results[0].input_message_content.rich_message.html, /Gram History/);
});

test('chosen result edits the selected inline message and survives a fresh handler instance', async () => {
  const answers = [], edits = [];
  await createInlineHandler({ answer: async value => answers.push(value) })({ id: 'listing', query: '24.04.22 UTC+5' });
  const handler = createChosenHandler({
    getPrice: async query => { assert.equal(query.params.timezone, 'Etc/GMT-5'); return daily; },
    edit: async params => edits.push(params),
  });
  await handler({ result_id: answers[0].results[0].id, query: '24.04.22 UTC+5', inline_message_id: 'sent-inline-id' });
  assert.equal(edits.length, 1);
  assert.equal(edits[0].inline_message_id, 'sent-inline-id');
  assert.match(JSON.stringify(edits[0].rich_message), /2,07000000000000001 USD/);
  const button = edits[0].rich_message.blocks.find(block => block.type === 'buttons').buttons.find(button => button.url);
  assert.equal(button.url, 'https://gram.rin.ms/docs');
  assert.equal(button.text[0].custom_emoji_id, '5884343982816759327');
  assert.deepEqual(edits[0].reply_markup, { inline_keyboard: [] });
});

test('chosen result handles price errors and ignores legacy or uneditable messages', async () => {
  const edits = [], logs = [];
  const handler = createChosenHandler({ getPrice: async () => { throw new PriceError('DATA_GAP'); }, edit: async params => edits.push(params), log: entry => logs.push(entry) });
  await handler({ result_id: 'old-format', inline_message_id: 'old', query: '24.04.22' });
  await handler({ result_id: 'load:test', query: '24.04.22' });
  assert.equal(edits.length, 0);
  assert.equal(logs[0].event, 'inline_chosen_no_id');
  await handler({ result_id: 'load:test', inline_message_id: 'gap', query: '24.04.22 15:30' });
  assert.match(edits[0].rich_message.html, /старше 15 минут/);
});

test('duplicate selections of one message coalesce; distinct sent messages each get edited', async () => {
  let reads = 0;
  const edits = [];
  const handler = createChosenHandler({ getPrice: async () => { reads++; return daily; }, edit: async params => edits.push(params) });
  const chosen = { result_id: 'load:test', inline_message_id: 'one', query: '24.04.22' };
  await Promise.all([handler(chosen), handler(chosen), handler({ ...chosen, inline_message_id: 'two' })]);
  assert.equal(reads, 2);
  assert.deepEqual(edits.map(p => p.inline_message_id).sort(), ['one', 'two']);
});

test('temporary edit failures respect Telegram retry_after and retry the same message', async () => {
  let calls = 0;
  const delays = [];
  const handler = createChosenHandler({
    getPrice: async () => daily,
    wait: async ms => delays.push(ms),
    edit: async params => {
      assert.equal(params.inline_message_id, 'retry');
      if (++calls === 1) throw Object.assign(new Error('Flood wait'), { code: 429, parameters: { retry_after: 2 } });
      if (calls === 2) throw Object.assign(new Error('Server error'), { code: 500 });
    },
  });
  await handler({ result_id: 'load:test', inline_message_id: 'retry', query: '24.04.22' });
  assert.equal(calls, 3);
  assert.deepEqual(delays, [2000, 500]);
});

test('rejected Rich Message becomes an actionable error instead of a permanent Loading', async () => {
  const edits = [], logs = [];
  const handler = createChosenHandler({ getPrice: async () => daily, log: entry => logs.push(entry), edit: async params => {
    edits.push(params);
    if (params.rich_message) throw Object.assign(new Error('Bad Request'), { code: 400 });
  } });
  await handler({ result_id: 'load:test', inline_message_id: 'rejected', query: '24.04.22' });
  assert.equal(edits.length, 2);
  assert.match(edits[1].text, /Повторите запрос/);
  assert.equal(edits[1].reply_markup.inline_keyboard[0][0].switch_inline_query, '24.04.22');
  assert.equal(logs[0].event, 'inline_edit_failed');
});
