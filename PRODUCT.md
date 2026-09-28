# Gram Prices
<!-- impeccable:product-schema 1 -->

## Platform
web

## Product Purpose
The user needs a fast, standardized API returning TON prices by historical timestamp and collecting new TON/USD observations every five minutes from Calcmula. The API is deployed at https://gram.rin.ms.

## Users
Developers integrating price-by-date and current-price queries; inferred directly from the user's API and documentation request. Documentation language follows the user's Russian conversation. API field names and code remain English.

## Capabilities and Constraints
- 451000 Telegram archive observations beginning 2021-12-15. Historical labels are USD. The user explicitly requires new Calcmula quotes in USD (1 ton in usd). Previously collected USDT observations stay correctly labeled in calcmula-usdt; calcmula-usd is the active series. Reference follows both cutovers; currencies must remain distinguishable.
- Price lookup returns the latest observation no later than the requested timestamp, with default maximum age 900 seconds. No interpolation and no made-up missing points.
- User-confirmed addition: `/v1/ton/price?at=YYYY-MM-DD` returns a daily summary (first, last, minimum, maximum), with an optional IANA timezone defaulting to UTC. RFC3339 still returns one observation. Today's summary is partial; future dates fail; currency segments stay separate. The console starts with a simple date and explains both forms.
- Endpoints: historical price, latest, paginated history, daily statistics, coverage, health. Success data/meta; RFC9457 errors; prices as exact strings.
- Calcmula collection every 300 seconds. Its underlying quote timestamp is unknown, so observed_at is retrieval time.
- Existing Python FastAPI + SQLite and Docker deployment. The documentation must ship within this app, preserve API behavior, and never modify prices.
- Work runs on the server, not as a background service on the user's PC.

## Brand Commitments

The user explicitly requires dark theme by default. Keep the optional light theme and preserve an explicitly saved theme choice.
The user originally referenced calcmula.app for documentation functionality and explicitly rejected a 1:1 copy. On 2026-09-28 they authorized a full replacement visual world and supplied a blue square logo: a graphite circular history arrow around a diamond/star. Use this image as the logo, stored unchanged as tonprices/static_docs/gram-history.png. Sky blue and graphite now ground the identity. The deployed hostname is gram.rin.ms; stable API asset_id remains toncoin.

## Website Surfaces

- `/`: separate homepage with description, live request tester, source attribution, AI/skill.md block and Telegram bot entry. All prices from 2021-12-15 through 2026-09-27 are attributed to @tonprices with a link; later collection is attributed to calcmula.app every five minutes. Detailed currency provenance remains in the reference.
- `/docs`: dedicated API reference with navigation, search, parameters, date/time semantics, source/currency policies, response format and errors. Method test links return to the homepage with the method selected.
- `/skill.md`: existing plain Markdown integration instructions; `/openapi.json` and `/swagger` remain available.
- Theme choice persists across pages; no new external frontend runtime, backend service or API dependency is introduced.

## Evidence on Hand
README.md, openapi.json, tonprices/app.py and tests describe the actual contract. The verified historical example is 2024-02-05T09:00:00Z -> 2.05 USD at 08:58:16Z, age 104 seconds. Any current price or health status must come from a live request, never from invented demo data.

## Product Principles
Make the first useful request easy to copy and run. Explain the timestamp and source alongside the value. Keep full reference details discoverable without making the introduction dense. Preserve working raw OpenAPI and interactive Swagger as secondary developer tools.

User refinement2026-09-28: SF Pro Display primary UI family, served as WOFF2 including Cyrillic; moderately rounded controls and surfaces with quiet neutral boundaries; remove hero fact strip and footer slogan.

Full SQLite gzip export at /v1/ton/export, prepared by a separate worker every 300 seconds. Home links to the public GitHub repository and complete database download.
