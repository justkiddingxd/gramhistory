import { DateTime, FixedOffsetZone, IANAZone } from 'luxon';
import { readRelative } from './relative.js';

export const DEFAULT_ZONE = 'Europe/Moscow';
export class QueryError extends Error {}

function timezone(value) {
  if (!value || /^(?:мск|msk)$/i.test(value)) return DEFAULT_ZONE;
  if (/^(?:utc|gmt|z)$/i.test(value)) return 'UTC';
  const offset = /^(?:(?:utc|gmt)\s*)?([+-])(\d{1,2})(?::?(\d{2}))?$/i.exec(value);
  if (offset) {
    const hours = Number(offset[2]), minutes = Number(offset[3] || 0);
    if (hours > 14 || minutes > 59 || (hours === 14 && minutes)) throw new QueryError('Неверное смещение UTC. Например: UTC+5 или UTC+05:30.');
    return FixedOffsetZone.instance((offset[1] === '-' ? -1 : 1) * (hours * 60 + minutes));
  }
  if (!IANAZone.isValidZone(value)) throw new QueryError('Неизвестный часовой пояс. Например: МСК, UTC+5 или Europe/Berlin.');
  return value;
}

export function zoneLabel(moment) {
  return `${moment.zoneName === DEFAULT_ZONE ? 'МСК' : moment.zoneName} (UTC${moment.toFormat('ZZ')})`;
}

export function parseQuery(input, { now = DateTime.utc() } = {}) {
  const text = String(input).trim().replace(/\s+/g, ' ');
  if (!text) return { kind: 'help' };
  if (text.length > 256) throw new QueryError('Запрос слишком длинный. Пример: 24.04.22 15:30.');
  const match = /^(?:(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})|(\d{4})-(\d{2})-(\d{2}))(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?(?:\s*(Z|[+-]\d{2}:?\d{2})|\s+(.+))?$/i.exec(text);
  if (!match) {
    const relative = readRelative(text);
    if (relative) return relativeQuery(relative, now);
    throw new QueryError('Введите дату 24.04.22, «сегодня», «вчера 15:30» или «3 дня назад». English: today, yesterday, 3 days ago.');
  }
  const year = match[3] ? Number(match[3]) + (match[3].length === 2 ? 2000 : 0) : Number(match[4]);
  const month = Number(match[2] || match[5]), day = Number(match[1] || match[6]);
  const hasTime = match[7] !== undefined;
  const hour = Number(match[7] || 0), minute = Number(match[8] || 0), second = Number(match[9] || 0);
  if (hour > 23 || minute > 59 || second > 59) throw new QueryError('Время должно быть от 00:00:00 до 23:59:59.');
  const explicitZone = match[10] || match[11];
  const zone = timezone(explicitZone);
  const moment = DateTime.fromObject({ year, month, day, hour, minute, second }, { zone });
  if (!moment.isValid || moment.year !== year || moment.month !== month || moment.day !== day) throw new QueryError('Такой даты нет в календаре. Проверьте день, месяц и год.');
  if (hasTime && (moment.hour !== hour || moment.minute !== minute || moment.second !== second)) throw new QueryError('Такого местного времени нет из-за перевода часов. Укажите время со смещением UTC.');
  if (hasTime && moment.getPossibleOffsets().length > 1) throw new QueryError('В этот день часы переводили назад: время неоднозначно. Укажите смещение, например UTC+2.');
  return buildQuery(moment, hasTime, zone, explicitZone, now);
}

function relativeQuery(relative, now) {
  const { unit, amount, explicitZone, hasClock, hour, minute, second } = relative;
  const zone = timezone(explicitZone);
  const isDuration = ['seconds', 'minutes', 'hours'].includes(unit);
  if (hasClock && isDuration) throw new QueryError('После «сейчас» или «час назад» время не нужно. Для времени суток укажите, например, «сегодня 15:30».');
  if (hour > 23 || minute > 59 || second > 59) throw new QueryError('Время должно быть от 00:00:00 до 23:59:59.');
  const referenceAt = Math.floor(now.toSeconds());
  const localNow = DateTime.fromSeconds(referenceAt, { zone });
  let moment = isDuration ? localNow.minus({ [unit]: amount }) : localNow.startOf('day').minus({ [unit]: amount });
  if (!moment.isValid || moment.year < 1 || moment.year > 9999) throw new QueryError('Слишком большой отступ от текущей даты. Например: 3 дня назад или 2 years ago.');
  if (hasClock) {
    const date = { year: moment.year, month: moment.month, day: moment.day, hour, minute, second };
    moment = DateTime.fromObject(date, { zone });
    if (!moment.isValid || moment.hour !== hour || moment.minute !== minute || moment.second !== second) throw new QueryError('Такого местного времени нет из-за перевода часов. Укажите время со смещением UTC.');
    if (moment.getPossibleOffsets().length > 1) throw new QueryError('В этот день часы переводили назад: время неоднозначно. Укажите смещение, например UTC+2.');
  }
  return { ...buildQuery(moment, isDuration || hasClock, zone, explicitZone, now), referenceAt };
}

function buildQuery(moment, hasTime, zone, explicitZone, now) {
  const limit = hasTime ? now.toMillis() : now.setZone(zone).startOf('day').toMillis();
  if (moment.toMillis() > limit) throw new QueryError('Эта дата ещё не наступила. Будущий курс неизвестен.');
  let apiZone = typeof zone === 'string' ? zone : null;
  if (!hasTime && !apiZone) {
    if (moment.offset % 60) throw new QueryError('Для сводки за день укажите пояс города, например Asia/Kolkata. Смещение с минутами поддерживается для точного времени.');
    apiZone = moment.offset === 0 ? 'UTC' : `Etc/GMT${moment.offset > 0 ? '-' : '+'}${Math.abs(moment.offset / 60)}`;
    if (!IANAZone.isValidZone(apiZone)) throw new QueryError('Для сводки за день укажите часовой пояс города, например Pacific/Auckland.');
  }
  return {
    kind: hasTime ? 'point' : 'daily',
    moment,
    zone: moment.zone,
    label: zoneLabel(moment),
    defaultZone: !explicitZone,
    params: hasTime ? { at: moment.toUTC().toISO({ suppressMilliseconds: true }) } : { at: moment.toISODate(), timezone: apiZone },
  };
}
