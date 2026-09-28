# Развёртывание Gram Prices

Подготовка новой базы и первый запуск описаны в [README.md](README.md). Не заменяйте действующую базу старой копией.

## Сервисы

- `api`: FastAPI, только `127.0.0.1:8087`; публичный HTTPS настраивается обратным прокси.
- `collector`: TON/USD из Calcmula каждые 5 минут.
- `exporter`: согласованный SQLite gzip каждые 5 минут, ограничен 0.5 CPU и 256 MB RAM.
- `bot`: puregram, необязательный; токен в Docker secret.
- `init`: одноразовая миграция схемы перед запуском.

База находится в `data/ton-prices.sqlite3`. Для SQLite WAL необходим доступ к этому каталогу. Готовые снимки лежат в volume `price_exports`, смонтированном у API только для чтения. Оставляется текущий и предыдущий снимок. Нужен запас места под рабочую копию базы и сжатые файлы. Ошибка создания снимка не заменяет предыдущий файл; спустя 15 минут API перестаёт отдавать устаревший экспорт.

## Управление

```sh
docker compose ps
docker compose logs --tail=30 api collector exporter
docker compose up -d --build api collector exporter
```

Чтобы обновить только API и экспорт:

```sh
docker compose build api
docker compose up -d --no-deps --no-build api exporter
```

`docker compose down` останавливает сервисы с сохранением данных. Не добавляйте `--volumes`, если хотите сохранить подготовленные выгрузки. Исходная SQLite находится в bind mount `./data`, отдельно от Docker volume.

## Проверка

```sh
curl --fail http://127.0.0.1:8087/health/ready
curl --head http://127.0.0.1:8087/v1/ton/export
curl --fail --output backup.sqlite3.gz http://127.0.0.1:8087/v1/ton/export
```

Первый снимок готовится после запуска exporter: до окончания API возвращает 503 `EXPORT_UNAVAILABLE`. Размер и время снимка — в заголовках HEAD. После распаковки проверьте `PRAGMA integrity_check` перед восстановлением. Обычное копирование открытого `.sqlite3` без WAL не является корректной резервной копией.

Для самостоятельного процесса экспорта вне Docker:

```sh
python -m tonprices.exporter --db data/ton-prices.sqlite3 --directory exports --loop
```

У API задайте тот же каталог в `TONPRICES_EXPORT_DIR`. Без `--loop` создаётся один снимок. Параметр `TONPRICES_DB` задаёт путь к базе для всех Python-компонентов. Не запускайте два exporter в один каталог.

Инструкция бота и настройки BotFather — [bot/README.md](bot/README.md).
