import { setTimeout as sleep } from 'node:timers/promises';
import { DateTime } from 'luxon';
import { parseQuery, QueryError } from './query.js';
import { helpResult, loadingResult, noticeResult, priceResult, errorResult } from './render.js';

export function createInlineHandler({ answer, log = () => {}, clock = () => DateTime.utc() }) {
  return async raw => {
    const started = performance.now();
    if (raw.offset) {
      await answer({ inline_query_id: raw.id, results: [], is_personal: true, cache_time: 0, next_offset: '' });
      return;
    }
    let result;
    let kind = 'help';
    try {
      const query = parseQuery(raw.query, { now: clock() });
      kind = query.kind;
      result = query.kind === 'help' ? helpResult() : loadingResult(query, raw.query);
    } catch (error) {
      kind = 'notice';
      result = error instanceof QueryError ? noticeResult('Проверьте дату и время', error.message) : errorResult(error);
    }
    await answer({ inline_query_id: raw.id, results: [result], is_personal: true, cache_time: 0, next_offset: '' });
    // Keep operational metrics without recording user IDs, queries or message text.
    log({ event: 'inline_answered', kind, elapsed_ms: Math.round(performance.now() - started) });
  };
}

export function createChosenHandler({ getPrice, edit, log = () => {}, wait = sleep, clock = () => DateTime.utc() }) {
  const pending = new Map();
  async function editWithRetry(params) {
    for (let attempt = 0; ; attempt++) {
      try { return await edit(params); }
      catch (error) {
        if (error.code === 400 && /message is not modified/i.test(error.message)) return;
        const transient = !Number.isInteger(error.code) || error.code === 429 || error.code >= 500;
        const delay = error.code === 429 ? (error.parameters?.retry_after ?? 1) * 1000 : 250 * 2 ** attempt;
        if (!transient || attempt >= 2 || delay > 30000) throw error;
        await wait(delay);
      }
    }
  }
  async function finish(raw) {
    const started = performance.now();
    let result, kind = 'notice';
    try {
      const anchor = /^load:r([0-9a-z]+):[a-f0-9]{16}$/.exec(raw.result_id);
      const query = parseQuery(raw.query, { now: anchor ? DateTime.fromSeconds(parseInt(anchor[1], 36)) : clock() });
      kind = query.kind;
      result = query.kind === 'help' ? helpResult() : priceResult(query, await getPrice(query));
    } catch (error) {
      kind = 'notice';
      result = error instanceof QueryError ? noticeResult('Проверьте дату и время', error.message) : errorResult(error);
    }
    try {
      await editWithRetry({
        inline_message_id: raw.inline_message_id,
        rich_message: result.input_message_content.rich_message,
        reply_markup: { inline_keyboard: [] },
      });
      log({ event: 'inline_edited', kind, elapsed_ms: Math.round(performance.now() - started) });
    } catch (error) {
      log({ event: 'inline_edit_failed', code: Number.isInteger(error.code) ? error.code : undefined });
      // Replace a failed placeholder with an actionable message instead of leaving Loading forever.
      await editWithRetry({
        inline_message_id: raw.inline_message_id,
        text: 'Не удалось показать карточку. Повторите запрос через несколько секунд.',
        reply_markup: { inline_keyboard: [[{ text: 'Повторить запрос', switch_inline_query: raw.query }]] },
      });
    }
  }
  return async raw => {
    if (!raw.result_id?.startsWith('load:')) return;
    if (!raw.inline_message_id) { log({ event: 'inline_chosen_no_id' }); return; }
    if (pending.has(raw.inline_message_id)) return pending.get(raw.inline_message_id);
    const task = finish(raw).finally(() => pending.delete(raw.inline_message_id));
    pending.set(raw.inline_message_id, task);
    return task;
  };
}
