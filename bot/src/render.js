import { createHash } from 'node:crypto';
import { DateTime } from 'luxon';
import { InlineQueryResult, InputMessageContent } from 'puregram';

export const escapeHtml = (value) => String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
const e = escapeHtml;
const price = value => e(String(value).replace('.', ','));
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
  const hash = createHash('sha256').update(input).digest('hex');
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
  return '<details><summary>Об источнике</summary><p>Все цены GRAM начиная с 15 декабря 2021 года и заканчивая 27 сентября 2026 года взяты из канала <a href="https://t.me/tonprices">@tonprices</a>. Дальнейшая поддержка базы данных работает через <a href="https://calcmula.app">calcmula.app</a>, отправляя запрос каждые 5 минут.</p></details>';
}

export function priceResult(query, body) {
  const data = body.data;
  const day = query.moment.toFormat('dd.MM.yyyy');
  const zone = `${e(query.label)}${query.defaultZone ? ' · по умолчанию' : ''}`;
  const local = value => DateTime.fromISO(value, { setZone: true }).setZone(query.zone).toFormat('dd.MM.yyyy HH:mm:ss');
  if (query.kind === 'daily') {
    if (!data.segments.length) return noticeResult(`GRAM · ${day}: нет данных`, `За этот день (${query.label}) в архиве нет наблюдений. Это не нулевая цена.`);
    const segments = data.segments.map(segment => {
      const currency = e(segment.quote_currency);
      const rows = [[`${icon('first')} Первая цена`, segment.first], [`${icon('last')} Последняя цена`, segment.last], [`${icon('max')} Максимум`, segment.max], [`${icon('min')} Минимум`, segment.min]];
      return `<table bordered striped><tr><th>Показатель</th><th>Значение</th></tr>` +
        rows.map(([label, value]) => `<tr><td>${label}</td><td><b>${price(value)} ${currency}</b></td></tr>`).join('') +
        `<tr><td>${icon('first')} Первая запись</td><td><code>${e(local(segment.first_at))}</code></td></tr>` +
        `<tr><td>${icon('last')} Последняя запись</td><td><code>${e(local(segment.last_at))}</code></td></tr>` +
        `<tr><td>${icon('observations')} Наблюдений</td><td><b>${e(segment.points_count)}</b></td></tr></table>`;
    }).join('');
    const notes = [];
    if (data.segments.some(segment => segment.max_gap_seconds > 900)) notes.push('Пропуски >15 мин');
    notes.push('Min/max по сохранённым данным');
    const dailyFooter = `<footer>${notes.map(e).join(' · ')}</footer>`;
    const single = data.segments.length === 1 ? data.segments[0] : null;
    const description = single ? `От ${String(single.min).replace('.', ',')} до ${String(single.max).replace('.', ',')} ${single.quote_currency} · ${query.label}` : `Сводка по ${data.segments.length} источникам и валютам · ${query.label}`;
    return result({ title: `GRAM · ${day} · за день`, description, query: day,
      html: `<h2>${icon('gram')} GRAM · ${day}</h2><p>${icon('summary')} Сводка за день · ${zone}</p>` +
        (!data.is_day_complete ? '<p><b>День ещё идёт — сводка неполная.</b></p>' : '') + segments +
        (data.segments.length > 1 ? '<p>Источники и валюты показаны отдельно. USD и USDT не пересчитываются друг в друга.</p>' : '') +
        sourceNotes() + dailyFooter,
    });
  }
  return result({ title: `GRAM · ${day} ${query.moment.toFormat('HH:mm')} · ${data.price} ${data.quote_currency}`,
    description: `Запись: ${local(data.observed_at)} · ${query.label}`,
    query: `${day} ${query.moment.toFormat('HH:mm')}`,
    html: `<h2>${icon('gram')} GRAM · ${day}</h2><p><b>1 GRAM = ${price(data.price)} ${e(data.quote_currency)}</b></p>` +
      `<table compact><tr><td>Запрошено</td><td>${e(local(data.requested_at))}</td></tr><tr><td>Найдена запись</td><td>${e(local(data.observed_at))}</td></tr><tr><td>Часовой пояс</td><td>${zone}</td></tr></table>` +
      `<p>Запись за ${e(data.age_seconds)} с до указанного момента.</p>` + sourceNotes() + footer,
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
