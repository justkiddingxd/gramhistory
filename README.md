Вживую: **[gram.rin.ms](https://gram.rin.ms/)** — проверить запросы, посмотреть документацию и скачать базу.

# Gram Prices

История курсов GRAM / TON с 15 декабря 2021 года, быстрый HTTP API и inline-бот [@gramhistorybot](https://t.me/gramhistorybot) на puregram.

Все цены GRAM начиная с 15 декабря 2021 года и заканчивая 27 сентября 2026 года взяты из канала [@tonprices](https://t.me/tonprices). Дальнейшая поддержка базы данных работает через [calcmula.app](https://calcmula.app/), отправляя запрос каждые 5 минут.

- [Документация](https://gram.rin.ms/docs), [OpenAPI](https://gram.rin.ms/openapi.json), [Swagger](https://gram.rin.ms/swagger).
- [skill.md для нейросетей](https://gram.rin.ms/skill.md).
- [Скачать полную базу SQLite (.gz)](https://gram.rin.ms/v1/ton/export).

## API

API-ключ не нужен. Приложение читает локальную SQLite; запросы пользователей не ждут Telegram или Calcmula.

```sh
# Первая, последняя, минимальная и максимальная цена за день
curl 'https://gram.rin.ms/v1/ton/price?at=2024-02-05&timezone=Europe/Moscow'

# Последняя сохранённая цена до точного момента
curl 'https://gram.rin.ms/v1/ton/price?at=2024-02-05T09:00:00Z'

# Текущая цена
curl 'https://gram.rin.ms/v1/ton/price/latest'
```

| Метод | Назначение |
|---|---|
| `GET /v1/ton/price?at=…` | RFC 3339 → цена; `YYYY-MM-DD` → сводка за день |
| `GET /v1/ton/price/latest` | Последняя цена с проверкой свежести |
| `GET /v1/ton/history?from=…&to=…` | История с пагинацией; `[from,to)`, до 366 дней, `limit` до 1000 |
| `GET /v1/ton/daily?date=…` | Дневная сводка, IANA `timezone`, по умолчанию UTC |
| `GET /v1/ton/coverage` | Границы архива, серии и состояние сборщика |
| `GET /v1/ton/export` | Вся база SQLite, сжатая gzip; также поддерживается HEAD |
| `GET /health/live`, `GET /health/ready` | Проверки работоспособности |

JSON-успех имеет форму `{data, meta}`, ошибки — `application/problem+json` по RFC 9457. `X-Request-ID` возвращается для каждого запроса. Цены остаются десятичными строками: используйте `Decimal`, без дополнительного округления.

Точное время требует RFC 3339 с секундами и часовым поясом. В URL кодируйте `+` как `%2B`. Выбирается только запись не позднее запроса, без интерполяции; `max_age_seconds` по умолчанию 900, допустимо 0–86400. Простая дата возвращает `data.kind="daily_summary"`; сегодня — неполный день, будущая дата — 422, день без данных — пустая сводка с `NO_DATA`.

### Источники и валюты

`series=reference` выбирает архив Telegram USD, затем прежний участок Calcmula USDT, затем нынешние Calcmula USD. Моменты переключения доступны в `/coverage` как `cutover_at` и `usd_cutover_at`. Явный выбор: `telegram-usd`, `calcmula-usdt`, `calcmula-usd`. `market-usdt` зарезервирован и пуст.

USD и USDT сохраняются отдельно, без пересчёта. Суточные сводки разделяют разные валюты на сегменты. USD в архиве следует из знака `$` в исходных сообщениях; первичный поставщик котировок неизвестен. Время Calcmula означает получение ответа, поскольку провайдер не сообщает время обновления курса. Сборщик запрашивает `1 ton in usd` и сохраняет точное `result.amount`, а не округлённое `formatted`.

### Полная выгрузка

```sh
curl --fail --location --output gram-prices.sqlite3.gz https://gram.rin.ms/v1/ton/export
gzip --decompress gram-prices.sqlite3.gz
sqlite3 gram-prices.sqlite3 'SELECT count(*) FROM price_observations;'
```

В файле все серии, исходные сообщения публичного канала, метаданные и состояние сборщика. Таблицы: `prices`, `live_prices`, `raw_messages`, `metadata`, `collector_state`; общее представление — `price_observations`. `raw_messages.raw_json_zlib` хранит исходный JSON, сжатый zlib.

Отдельный `exporter` готовит согласованный снимок через SQLite backup API каждые 5 минут, включая зафиксированные записи WAL. API отдаёт готовый файл потоком; создание и сжатие не выполняются внутри запроса. Это бинарный `application/gzip`, без JSON-оболочки и без HTTP `Content-Encoding`.

`HEAD /v1/ton/export` возвращает размер, имя файла, `X-Snapshot-Created-At`, `X-Snapshot-Age-Seconds` и `X-Checksum-SHA256` (хэш сжатого файла). `ETag` + `If-None-Match` позволяют получить 304 без повторного скачивания. Снимок старше 15 минут — 503 `EXPORT_STALE`; ещё не готов — 503 `EXPORT_UNAVAILABLE`; повторите через `Retry-After`. Частичная загрузка Range не поддерживается. Ошибки остаются в стандартном JSON-формате.

## Запуск на своём сервере

Нужны Docker и Docker Compose. Для новой установки:

```sh
git clone https://github.com/justkiddingxd/gramhistory.git
cd gramhistory
mkdir -p data
curl --fail --location --output data/initial.sqlite3.gz https://gram.rin.ms/v1/ton/export
gzip --decompress --stdout data/initial.sqlite3.gz > data/ton-prices.sqlite3
docker compose up -d --build api collector exporter
```

API слушает `127.0.0.1:8087`; для публичного HTTPS поставьте Nginx/Caddy перед ним. Существующую пополняемую базу не заменяйте старой выгрузкой. База не хранится в Git. Для импорта собственного Telegram JSON: `python -m tonprices.importer result.json --db data/ton-prices.sqlite3`; установленное Python-окружение требует `requirements.txt`.

Сервисы: `api` — FastAPI, `collector` — котировка раз в 5 минут, `exporter` — полная выгрузка, `bot` — необязательный Telegram-бот. Экспорт хранится в Docker volume `price_exports`, API монтирует его только для чтения. Не запускайте несколько сборщиков для одной базы.

Для бота создайте `secrets/telegram_bot_token`, доступный UID 1000, и запустите `docker compose up -d --build bot`. Токен не коммитьте. В BotFather включите inline и inline feedback 100%. Подробности и русские/английские алиасы — в [bot/README.md](bot/README.md). Управление сервером — [DEPLOYMENT.md](DEPLOYMENT.md).

В карточках бота используется одна сводка в USD; прежние USDT показываются условно 1:1 с пометкой в footer. Это правило представления бота: API и полная выгрузка сохраняют оригинальные валюты.

## Структура

```text
tonprices/app.py          API, валидация, ответы
tonprices/db.py           схема SQLite и подключения
tonprices/importer.py     импорт Telegram JSON
tonprices/collector.py    сбор TON/USD из Calcmula
tonprices/exporter.py     подготовка полных снимков
tonprices/download.py     потоковая выдача готового снимка
tonprices/static_docs/   главная и документация
tonprices/skills/        публичный skill.md
bot/                     inline-бот на puregram
tests/                   тесты API, импорта, сбора и выгрузки
```

Главная и справочник используют тёмную тему по умолчанию, SF Pro Display с кириллицей и IBM Plex Mono для кода. Исходные лицензии шрифтов находятся рядом с файлами в `tonprices/static_docs/fonts/`.

## Проверки

```sh
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
cd bot
npm ci
npm test
```

Тесты проверяют точность цен, выбор предыдущей записи, UTC/DST, пагинацию, ошибки, переходы источников и валют, сбор без дублей и восстановление после сбоя. Для выгрузки проверяются WAL, целостность восстановленной базы, все таблицы, контрольная сумма, HEAD/ETag, устаревание и обновление файла во время скачивания. Измерения запросов на сервере — [PERFORMANCE.md](PERFORMANCE.md).

Для Python urllib передавайте `User-Agent: GramPricesClient/1.0`: стандартную подпись urllib может отклонить Cloudflare до обращения к API.
