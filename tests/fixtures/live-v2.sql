CREATE TABLE IF NOT EXISTS live_prices(
 id INTEGER PRIMARY KEY,
 series_id TEXT NOT NULL CHECK(series_id='calcmula-usdt'),
 source TEXT NOT NULL CHECK(source='calcmula'),
 sample_bucket INTEGER NOT NULL UNIQUE,
 observed_at INTEGER NOT NULL,
 received_at TEXT NOT NULL,
 price TEXT NOT NULL,
 quote_currency TEXT NOT NULL CHECK(quote_currency='USDT'),
 expression TEXT NOT NULL,
 response_json TEXT NOT NULL,
 http_date TEXT,
 provider_updated_at INTEGER,
 CHECK(observed_at>=sample_bucket AND observed_at<sample_bucket+300)
);
