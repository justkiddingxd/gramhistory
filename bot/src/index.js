import { readFileSync, writeFileSync } from 'node:fs';
import { Telegram } from 'puregram';
import { createPriceClient } from './prices.js';
import { createInlineHandler, createChosenHandler } from './inline.js';
import { parseQuery, QueryError } from './query.js';
import { helpResult, noticeResult, priceResult, errorResult } from './render.js';

const log = value => console.log(JSON.stringify(value));
const safeError = (event, error) => log({ event, type: error?.name || 'Error', code: Number.isInteger(error?.code) ? error.code : undefined });

async function main() {
  const token = process.env.TELEGRAM_BOT_TOKEN?.trim() || readFileSync(process.env.TELEGRAM_BOT_TOKEN_FILE || '/run/secrets/telegram_bot_token', 'utf8').trim();
  if (!/^\d+:[A-Za-z0-9_-]+$/.test(token)) throw new Error('Invalid token');
  const telegram = Telegram.fromToken(token, { apiTimeout: 35000, apiRetryLimit: -1, apiWait: 1000, swallowDispatchErrors: true, dedupeUpdates: true });
  const getPrice = createPriceClient(process.env.PRICES_API_URL || 'http://api:8087');
  let lastPoll = Date.now();
  let stopping = false;
  const counters = { inline_answered: 0, inline_edited: 0, inline_edit_failed: 0, inline_chosen_no_id: 0, inline_errors: 0, private_answered: 0 };
  const metrics = value => { if (value.event in counters) counters[value.event]++; log(value); };
  telegram.useHook('onAfterRequest', async (ctx, next) => {
    if (ctx.method === 'getUpdates') lastPoll = Date.now();
    await next();
  });
  telegram.useHook('onError', (error, ctx) => { safeError(`telegram_${ctx.method || 'request'}_error`, error); });
  telegram.catch(error => { counters.inline_errors++; safeError('update_error', error); });
  const handleInline = createInlineHandler({ answer: params => telegram.api.answerInlineQuery(params), log: metrics });
  const handleChosen = createChosenHandler({ getPrice, edit: params => telegram.api.editMessageText(params), log: metrics });
  telegram.onInlineQuery(context => handleInline(context.raw));
  telegram.onChosenInlineResult(context => handleChosen(context.raw));
  telegram.onMessage(async context => {
    const message = context.raw;
    if (message.chat?.type !== 'private' || !message.text || message.from?.is_bot) return;
    let result;
    try {
      const command = /^\/(?:start|help)(?:@gramhistorybot)?(?:\s.*)?$/i.test(message.text);
      const query = command ? { kind: 'help' } : parseQuery(message.text);
      result = query.kind === 'help' ? helpResult() : priceResult(query, await getPrice(query));
    } catch (error) {
      result = error instanceof QueryError ? noticeResult('Проверьте дату и время', error.message) : errorResult(error);
    }
    const reply_markup = { inline_keyboard: [[{ text: 'Попробовать в чате', switch_inline_query: '24.04.22' }]] };
    await telegram.api.sendRichMessage({ chat_id: message.chat.id, rich_message: result.input_message_content.rich_message, reply_markup });
    metrics({ event: 'private_answered' });
  });
  const me = await telegram.api.getMe();
  if (me.username !== 'gramhistorybot') throw new Error('Unexpected bot username');
  const webhook = await telegram.api.getWebhookInfo();
  if (webhook.url) throw new Error('Existing webhook must be reviewed before polling');
  await telegram.api.setMyCommands({ commands: [{ command: 'start', description: 'Как узнать курс GRAM на дату' }, { command: 'help', description: 'Даты словами, время и часовые пояса' }] });
  await telegram.api.setMyDescription({ description: 'История курса GRAM с декабря 2021 года. В любом чате: @gramhistorybot сегодня, yesterday, месяц назад, 3 days ago at 15:30 или 24.04.22. Сводки за день и цена на момент, Rich Messages. По умолчанию МСК.' });
  await telegram.api.setMyShortDescription({ short_description: 'Курс GRAM: сегодня, yesterday, месяц назад или 24.04.22 15:30. Inline: @gramhistorybot · По умолчанию МСК.' });
  await telegram.startPolling({ allowedUpdates: ['inline_query', 'chosen_inline_result', 'message'], timeout: 25, concurrency: 16, maxInFlight: 32 });
  const health = () => {
    writeFileSync('/tmp/gramhistory-health.json', JSON.stringify({ updated_at: Date.now(), last_poll_at: lastPoll, ...counters }));
    if (!stopping && Date.now() - lastPoll > 180000) { log({ event: 'polling_stalled' }); process.exit(1); }
  };
  health();
  const timer = setInterval(health, 15000);
  log({ event: 'bot_started', username: me.username, inline_enabled: Boolean(me.supports_inline_queries), default_timezone: 'Europe/Moscow' });
  const shutdown = async () => {
    if (stopping) return;
    stopping = true;
    clearInterval(timer);
    const deadline = setTimeout(() => process.exit(0), 10000);
    deadline.unref();
    await telegram.shutdown();
    process.exit(0);
  };
  process.once('SIGTERM', shutdown);
  process.once('SIGINT', shutdown);
}

main().catch(error => { safeError('startup_failed', error); process.exit(1); });
