import { createHash } from 'node:crypto';
import { DateTime } from 'luxon';
import { InlineQueryResult, InputMessageContent } from 'puregram';
import { displayCurrency, summarizeDay } from './summary.js';

export const escapeHtml = (value) => String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
const e = escapeHtml;
const price = value => String(value).replace('.', ',');
const icons = {
  max: ['5875078273775439450', '🔼'],
  min: ['5875008416132370818', '🔽'],
  api: ['5884343982816759327', '↗️'],
  date: ['5886666250158870040', '💬'],
  summary: ['5960551395730919906', '📝'],
  observations: ['5874960879434338403', '🔎'],
  first: ['5798535677318533269', '⏲'],
  last: ['5900006938271288826', '2️⃣'],
  gram: ['6006074913742396956', '💎'],
};
const icon = name => `<tg-emoji emoji-id="${icons[name][0]}">${icons[name][1]}</tg-emoji>`;
const richIcon = name => ({ type: 'custom_emoji', custom_emoji_id: icons[name][0], alternative_text: icons[name][1] });
const bold = text => ({ type: 'bold', text });
const paragraph = text => ({ type: 'paragraph', text });
const link = (text, url) => ({ type: 'url', text, url });
const cell = (text, header = false) => ({ text, align: 'left', valign: 'middle', ...(header ? { is_header: true } : {}) });
const approximationNote = 'USDT ≈ USD (1:1)';
const footer = '<footer><a href="https://gram.rin.ms/docs">Gram Prices</a> · История GRAM</footer>';

function result({ title, description, html, query = '' }) {
  const buttons = '<tg-button-row>' +
    `<tg-button type="switch_inline_query_current_chat" query="${e(query)}">${icon('date')} Другая дата</tg-button>` +
    `<tg-button type="url" url="https://gram.rin.ms/docs">${icon('api')} Об API</tg-button>` +
    '</tg-button-row>';
  const footerIndex = html.lastIndexOf('<footer>');
  const content = footerIndex < 0 ? html + buttons : html.slice(0, footerIndex) + buttons + html.slice(footerIndex);
  return InlineQueryResult.article({
    id: createHash('sha256').update(content).digest('hex').slice(0, 32),
    title,
    description: description.slice(0, 250),
    content: InputMessageContent.rich.html(content, { skipEntityDetection: true }),
  });
}

function blockResult({ title, description, blocks, footerText, query }) {
  const richMessage = {
    blocks: [...blocks, { type: 'buttons', buttons: [
      { text: [richIcon('date'), ' Другая дата'], switch_inline_query_current_chat: query },
      { text: [richIcon('api'), ' Об API'], url: 'https://gram.rin.ms/docs' },
    ] }, { type: 'footer', text: footerText }],
    skip_entity_detection: true,
  };
  return InlineQueryResult.article({
    id: createHash('sha256').update(JSON.stringify(richMessage)).digest('hex').slice(0, 32),
    title, description: description.slice(0, 250), content: { rich_message: richMessage },
  });
}

export function helpResult() {
  return result({
    title: 'Курс GRAM на дату',
    description: 'Дата или словами: сегодня, вчера, месяц назад, today. По умолчанию МСК.',
    query: '24.04.22',
    html: `<h2>${icon('gram')} Gram History</h2><p>Укажите дату после <b>@gramhistorybot</b> в любом чате.</p>` +
      '<table compact><tr><th>Запрос</th><th>Результат</th></tr><tr><td><code>24.04.22</code></td><td>Первая, последняя, минимум и максимум за день</td></tr>' +
      '<tr><td><code>24.04.22 15:30</code></td><td>Цена на этот момент</td></tr><tr><td><code>24.04.2022 15:30 UTC+5</code></td><td>Время с вашим смещением</td></tr>' +
      '<tr><td><code>сегодня</code> · <code>today</code></td><td>Сводка за текущий день</td></tr>' +
      '<tr><td><code>вчера</code> · <code>yesterday</code></td><td>Сводка за вчера</td></tr>' +
      '<tr><td><code>позавчера</code> · <code>day before yesterday</code></td><td>Два дня назад</td></tr>' +
      '<tr><td><code>месяц назад</code> · <code>last month</code></td><td>Та же дата месяц назад</td></tr>' +
      '<tr><td><code>3 дня назад в 15:30</code> · <code>3 days ago at 15:30</code></td><td>Цена в указанное время</td></tr>' +
      '<tr><td><code>сейчас</code> · <code>now</code> · <code>an hour ago</code></td><td>Цена на момент запроса или час назад</td></tr></table>' +
      '<p>По умолчанию <b>МСК · UTC+03:00</b>. Telegram не передаёт боту ваш часовой пояс. Его можно указать в запросе: <code>UTC+5</code> или <code>Europe/Berlin</code>.</p>' +
      '<p>Поддерживаются также <code>2022-04-24</code> и <code>2022-04-24T15:30:00+03:00</code>. Двузначный год означает 2000–2099.</p>' + footer,
  });
}

export function noticeResult(title, message) {
  return result({ title, description: message, html: `<h2>${e(title)}</h2><p>${e(message)}</p><p>Пример: <code>@gramhistorybot 24.04.22 15:30</code></p>${footer}` });
}

export function loadingResult(query, input) {
  const day = query.moment.toFormat('dd.MM.yyyy');
  const hash = createHash('sha256').update('usd-blocks-v2:' + input).digest('hex');
  return InlineQueryResult.article({
    // Preserve relative dates across midnight, selection delays and bot restarts.
    id: query.referenceAt === undefined ? 'load:' + hash.slice(0, 32) : `load:r${query.referenceAt.toString(36)}:${hash.slice(0, 16)}`,
    title: `GRAM · ${day} · ${query.kind === 'daily' ? 'за день' : query.moment.toFormat('HH:mm:ss')}`,
    description: `${query.kind === 'daily' ? 'Первая, последняя, максимум и минимум' : 'Цена на указанный момент'} · ${query.label}`,
    content: InputMessageContent.text('Loading...'),
    // Telegram provides inline_message_id only when an inline keyboard is attached.
    reply_markup: { inline_keyboard: [[{ text: 'Об API', url: 'https://gram.rin.ms/docs' }]] },
  });
}

function sourceNotes() {
  return { type: 'details', summary: 'Об источнике', blocks: [paragraph([
    'Все цены GRAM начиная с 15 декабря 2021 года и заканчивая 27 сентября 2026 года взяты из канала ',
    link('@tonprices', 'https://t.me/tonprices'), '. Дальнейшая поддержка базы данных работает через ',
    link('calcmula.app', 'https://calcmula.app/'), ', отправляя запрос каждые 5 минут.',
  ])] };
}

export function priceResult(query, body) {
  const data = body.data;
  const day = query.moment.toFormat('dd.MM.yyyy');
  const zone = `${query.label}${query.defaultZone ? ' · по умолчанию' : ''}`;
  const local = value => DateTime.fromISO(value, { setZone: true }).setZone(query.zone).toFormat('dd.MM.yyyy HH:mm:ss');
  if (query.kind === 'daily') {
    if (!data.segments.length) return noticeResult(`GRAM · ${day}: нет данных`, `За этот день (${query.label}) в архиве нет наблюдений. Это не нулевая цена.`);
    const summary = summarizeDay(data.segments);
    const rows = [['first', 'Первая цена', summary.first], ['last', 'Последняя цена', summary.last], ['max', 'Максимум', summary.max], ['min', 'Минимум', summary.min]];
    const table = { type: 'table', is_bordered: true, is_striped: true, cells: [
      [cell('Показатель', true), cell('Значение', true)],
      ...rows.map(([name, label, value]) => [cell([richIcon(name), ' ' + label]), cell(bold(`${price(value)} USD`))]),
      [cell([richIcon('first'), ' Первая запись']), cell({ type: 'code', text: local(summary.first_at) })],
      [cell([richIcon('last'), ' Последняя запись']), cell({ type: 'code', text: local(summary.last_at) })],
      [cell([richIcon('observations'), ' Наблюдений']), cell(bold(String(summary.points_count)))],
    ] };
    const notes = [];
    if (summary.max_gap_seconds > 900) notes.push('Пропуски >15 мин');
    notes.push('Min/max по сохранённым данным');
    if (summary.approximated) notes.push(approximationNote);
    return blockResult({ title: `GRAM · ${day} · за день`,
      description: `От ${price(summary.min)} до ${price(summary.max)} USD · ${query.label}`, query: day,
      blocks: [{ type: 'heading', size: 2, text: [richIcon('gram'), ` GRAM · ${day}`] },
        paragraph([richIcon('summary'), ` Сводка за день · ${zone}`]),
        ...(!data.is_day_complete ? [paragraph(bold('День ещё идёт — сводка неполная.'))] : []), table, sourceNotes()],
      footerText: notes.join(' · '),
    });
  }
  const { approximated } = displayCurrency(data.quote_currency);
  return blockResult({ title: `GRAM · ${day} ${query.moment.toFormat('HH:mm')} · ${data.price} USD`,
    description: `Запись: ${local(data.observed_at)} · ${query.label}`,
    query: `${day} ${query.moment.toFormat('HH:mm')}`,
    blocks: [{ type: 'heading', size: 2, text: [richIcon('gram'), ` GRAM · ${day}`] },
      paragraph(bold(`1 GRAM = ${price(data.price)} USD`)),
      { type: 'table', is_compact: true, cells: [
        [cell('Запрошено'), cell(local(data.requested_at))],
        [cell('Найдена запись'), cell(local(data.observed_at))],
        [cell('Часовой пояс'), cell(zone)],
      ] }, paragraph(`Запись за ${data.age_seconds} с до указанного момента.`), sourceNotes()],
    footerText: [link('Gram Prices', 'https://gram.rin.ms/docs'), ' · История GRAM', ...(approximated ? [' · ' + approximationNote] : [])],
  });
}

export function errorResult(error) {
  const messages = {
    PRICE_NOT_FOUND: 'До указанного момента нет записи. История начинается в декабре 2021 года.',
    DATA_GAP: 'Ближайшая предыдущая запись старше 15 минут. Точной цены на этот момент нет.',
    FUTURE_TIMESTAMP: 'Эта дата ещё не наступила. Будущий курс неизвестен.',
    PRICE_STALE: 'Источник пока не обновил цену. Попробуйте позже.',
    VALIDATION_ERROR: 'Проверьте дату и часовой пояс. Пример: 24.04.22 15:30 МСК.',
    BUSY: 'Сейчас много запросов. Повторите через несколько секунд.',
  };
  return noticeResult('Курс недоступен', messages[error.code] || 'Не удалось получить данные. Повторите запрос через несколько секунд.');
}
