const aliases = new Map();
function alias(names, unit, amount) {
  for (const name of names.split('|')) aliases.set(name, { unit, amount });
}
alias('сегодня|сег|today', 'days', 0);
alias('вчера|вч|yesterday|yday|yest', 'days', 1);
alias('позавчера|позавч|day before yesterday|the day before yesterday', 'days', 2);
alias('сейчас|теперь|текущий курс|актуальный курс|now|right now|latest|current|current price', 'seconds', 0);
alias('прошлая неделя|прошлую неделю|last week|previous week', 'weeks', 1);
alias('прошлый месяц|last month|previous month', 'months', 1);
alias('прошлый год|last year|previous year', 'years', 1);
alias('позапрошлая неделя|позапрошлую неделю', 'weeks', 2);
alias('позапрошлый месяц', 'months', 2);
alias('позапрошлый год', 'years', 2);
alias('полчаса назад|half an hour ago|half hour ago', 'minutes', 30);
alias('полгода назад|пол года назад|half a year ago|half year ago', 'months', 6);

const units = new Map();
for (const [unit, names] of [
  ['seconds', 'секунда|секунду|секунды|секунд|сек|с|second|seconds|sec|secs|s'],
  ['minutes', 'минута|минуту|минуты|минут|мин|minute|minutes|min|mins|m'],
  ['hours', 'час|часа|часов|ч|hour|hours|hr|hrs|h'],
  ['days', 'день|дня|дней|сутки|суток|д|day|days|d'],
  ['weeks', 'неделя|неделю|недели|недель|нед|н|week|weeks|wk|wks|w'],
  ['months', 'месяц|месяца|месяцев|мес|month|months|mo|mos'],
  ['years', 'год|года|лет|г|year|years|yr|yrs|y'],
]) for (const name of names.split('|')) units.set(name, unit);

const numbers = new Map();
for (const [amount, names] of [
  [1, 'один|одна|одно|одну|одни|a|an|one'],
  [2, 'два|две|пара|пару|two'], [3, 'три|three'], [4, 'четыре|four'],
  [5, 'пять|five'], [6, 'шесть|six'], [7, 'семь|seven'],
  [8, 'восемь|eight'], [9, 'девять|nine'], [10, 'десять|ten'],
]) for (const name of names.split('|')) numbers.set(name, amount);

// Deterministic grammar: no network requests or language-model calls on the query path.
export function readRelative(text) {
  let phrase = text;
  let explicitZone;
  const zone = /\s+((?:utc|gmt)(?:\s*[+-]\d{1,2}(?::?\d{2})?)?|z|мск|msk|[+-]\d{1,2}(?::?\d{2})?|[a-z][a-z0-9_+\-]*(?:\/[a-z0-9_+\-]+)+)$/i.exec(phrase);
  if (zone) { explicitZone = zone[1]; phrase = phrase.slice(0, zone.index); }
  const clock = /\s+(?:(?:в|at)\s+)?(\d{1,2}):(\d{2})(?::(\d{2}))?$/i.exec(phrase);
  if (clock) phrase = phrase.slice(0, clock.index);
  phrase = phrase.toLowerCase().replace(/ё/g, 'е').replace(/^(?:на|за|as of)\s+/, '');
  let relative = aliases.get(phrase);
  if (!relative) {
    const ago = /^(.+?)\s+(?:назад|ago)$/.exec(phrase);
    if (!ago) return null;
    const body = ago[1].replace(/\.$/, '');
    const quantity = /^(\d+)\s*(.+)$/.exec(body) || /^(\S+)\s+(.+)$/.exec(body);
    const unit = units.get(quantity ? quantity[2] : body);
    const amount = quantity ? (/^\d+$/.test(quantity[1]) ? Number(quantity[1]) : numbers.get(quantity[1])) : 1;
    if (!unit || !Number.isSafeInteger(amount) || amount < 0 || amount > 100000) return null;
    relative = { unit, amount };
  }
  return { ...relative, explicitZone, hasClock: Boolean(clock), hour: Number(clock?.[1] || 0), minute: Number(clock?.[2] || 0), second: Number(clock?.[3] || 0) };
}
