import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DateTime } from 'luxon';
import { parseQuery, QueryError } from '../src/query.js';
import { createInlineHandler, createChosenHandler } from '../src/inline.js';

const now = DateTime.fromISO('2026-09-28T12:00:00Z');
const parse = (input, at = now) => parseQuery(input, { now: at });

test('Russian and English date aliases resolve to the same calendar date', () => {
  for (const [inputs, expected] of [
    [['сегодня', 'TODAY', 'на сегодня', 'за сегодня', 'сег'], '2026-09-28'],
    [['вчера', 'yesterday', 'yday', 'as of yesterday'], '2026-09-27'],
    [['позавчера', 'day before yesterday', 'the day before yesterday'], '2026-09-26'],
    [['неделю назад', 'неделя назад', 'last week', 'a week ago', 'one week ago', 'прошлую неделю'], '2026-09-21'],
    [['месяц назад', 'last month', 'previous month', 'a month ago', 'прошлый месяц'], '2026-08-28'],
    [['год назад', 'last year', 'previous year', 'a year ago'], '2025-09-28'],
    [['3 дня назад', 'три дня назад', 'three days ago', '3d ago'], '2026-09-25'],
    [['две недели назад', 'пару недель назад', '2 weeks ago', '2нед назад', 'позапрошлая неделя'], '2026-09-14'],
    [['два месяца назад', 'two months ago', '2 mo ago', 'позапрошлый месяц'], '2026-07-28'],
    [['полгода назад', 'half a year ago', '6 месяцев назад'], '2026-03-28'],
    [['десять дней назад', 'ten days ago', '10 суток назад'], '2026-09-18'],
  ]) for (const input of inputs) {
    const query = parse(input);
    assert.equal(query.kind, 'daily', input);
    assert.equal(query.params.at, expected, input);
    assert.equal(query.params.timezone, 'Europe/Moscow', input);
    assert.equal(query.defaultZone, true, input);
  }
});

test('now and relative hours/minutes mean an instant rather than a daily summary', () => {
  for (const [inputs, expected] of [
    [['сейчас', 'now', 'right now', 'latest', 'текущий курс'], '2026-09-28T12:00:00Z'],
    [['час назад', 'an hour ago', 'one hour ago', '1h ago'], '2026-09-28T11:00:00Z'],
    [['полчаса назад', 'half an hour ago', '30 мин назад'], '2026-09-28T11:30:00Z'],
    [['две минуты назад', 'two minutes ago', '2min ago'], '2026-09-28T11:58:00Z'],
    [['30 секунд назад', '30 seconds ago'], '2026-09-28T11:59:30Z'],
  ]) for (const input of inputs) {
    const query = parse(input);
    assert.equal(query.kind, 'point', input);
    assert.equal(query.params.at, expected, input);
  }
});

test('natural dates accept a clock, optional at/в, and timezone', () => {
  for (const [input, expected] of [
    ['вчера 15:30', '2026-09-27T12:30:00Z'],
    ['вчера в 15:30:45', '2026-09-27T12:30:45Z'],
    ['Yesterday at 15:30 UTC+5', '2026-09-27T10:30:00Z'],
    ['  три   дня назад   в 9:05   МСК  ', '2026-09-25T06:05:00Z'],
    ['last month at 15:30 Europe/Berlin', '2026-08-28T13:30:00Z'],
    ['yesterday 12:00 UTC+05:30', '2026-09-27T06:30:00Z'],
  ]) assert.equal(parse(input).params.at, expected, input);
  assert.equal(parse('today UTC+5').params.timezone, 'Etc/GMT-5');
  assert.equal(parse('today UTC+5').defaultZone, false);
});

test('today and yesterday follow the requested timezone across midnight', () => {
  const at = DateTime.fromISO('2026-09-27T22:30:00Z');
  assert.equal(parse('today', at).params.at, '2026-09-28');
  assert.equal(parse('today UTC', at).params.at, '2026-09-27');
  assert.equal(parse('сегодня America/New_York', at).params.at, '2026-09-27');
  assert.equal(parse('вчера МСК', at).params.at, '2026-09-27');
});

test('calendar months and years clamp to the last valid day', () => {
  assert.equal(parse('месяц назад', DateTime.fromISO('2024-03-31T12:00:00Z')).params.at, '2024-02-29');
  assert.equal(parse('a month ago', DateTime.fromISO('2025-03-31T12:00:00Z')).params.at, '2025-02-28');
  assert.equal(parse('год назад', DateTime.fromISO('2024-02-29T12:00:00Z')).params.at, '2023-02-28');
});

test('relative dates keep validation for future clocks, DST, and unsupported expressions', () => {
  for (const input of ['сегодня 16:00', 'вчера 24:00', 'today at 12:60', 'now 15:30', '2 hours ago at 15:30', 'today Bad/Zone', 'yesterday UTC+15', 'today UTC+05:30', '1.5 days ago', '-3 days ago', '100001 years ago', 'завтра', '3 days ago trailing']) {
    assert.throws(() => parse(input), QueryError, input);
  }
  assert.throws(() => parse('yesterday at 02:30 Europe/Berlin', DateTime.fromISO('2024-04-01T12:00:00Z')), /перевода часов/);
  assert.throws(() => parse('yesterday at 02:30 Europe/Berlin', DateTime.fromISO('2024-10-28T12:00:00Z')), /неоднозначно/);
  assert.equal(parse('2 hours ago Europe/Berlin', DateTime.fromISO('2024-10-27T02:30:00Z')).params.at, '2024-10-27T00:30:00Z');
});

test('selection after midnight or a restart uses the date shown in the original result', async () => {
  const replies = [], edits = [], queries = [];
  const beforeMidnight = DateTime.fromISO('2026-09-27T20:59:59Z');
  const afterMidnight = DateTime.fromISO('2026-09-27T21:00:10Z');
  const inline = createInlineHandler({ answer: async p => replies.push(p), clock: () => beforeMidnight });
  await inline({ id: 'today', query: 'сегодня' });
  await inline({ id: 'now', query: 'now' });
  const handler = createChosenHandler({
    clock: () => afterMidnight,
    getPrice: async query => { queries.push(query); return { data: { segments: [] }, meta: {} }; },
    edit: async params => edits.push(params),
  });
  for (const [i, input] of ['сегодня', 'now'].entries()) {
    const result = replies[i].results[0];
    assert.ok(Buffer.byteLength(result.id) <= 64);
    assert.match(result.title, /27\.09\.2026/);
    await handler({ result_id: result.id, query: input, inline_message_id: String(i) });
  }
  assert.equal(queries[0].params.at, '2026-09-27');
  assert.equal(queries[1].params.at, '2026-09-27T20:59:59Z');
  assert.equal(edits.length, 2);
});
