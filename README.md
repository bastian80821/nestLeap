# NestLeap

Long-term stock analysis platform. Scores ~200 large-cap US stocks weekly using
Yahoo Finance fundamentals plus a Gemini-generated narrative, then runs a
simulated DCA portfolio that buys the top picks and benchmarks against the S&P 500.

Live: **[nestleap.au](https://nestleap.au)** — read-only for the public; write
endpoints require an admin key. An **iOS app** is currently in progress: a
Capacitor wrapper around the same Next.js bundle, runs in the simulator
against the live backend, not yet submitted to the App Store.

> The portfolio is **simulated** ($1,000/week paper DCA). The project does not
> place real trades and is not investment advice.

## Notable design decisions

- **Deterministic scoring + bounded LLM adjustment.** Sixteen sub-scores
  (quality, value, growth, momentum) are computed from raw fundamentals before
  any LLM call. Gemini then synthesises a narrative and may shift the overall
  score within a capped range — it can't invent a fair value out of thin air.
- **One Gemini call per stock.** Earlier iterations used a multi-agent setup
  (separate calls for news, fundamentals, valuation). Folding everything into a
  single prompt with structured output cut cost and latency ~5×.
- **SQLite, deliberately.** Working set is ~5 MB; query plans never matter at
  this scale. Avoids the operational tax of a separate database container.
- **Static frontend, single backend.** The web app and the in-progress iOS
  app ship the same Next.js bundle; the FastAPI backend is the only component
  holding credentials.

## Stack

| Layer            | Tech                                                  |
|------------------|-------------------------------------------------------|
| Web frontend     | Next.js 14 (App Router), Tailwind, TypeScript         |
| iOS app *(WIP)*  | Capacitor wrapping the static export of the web app   |
| Backend          | FastAPI, SQLAlchemy, SQLite                           |
| Data             | `yfinance`, RSS news scrapers                         |
| AI               | Google Gemini                                         |
| Infrastructure   | Docker Compose, Caddy (auto-HTTPS), single VPS        |

## Architecture

```
frontend/        Next.js — single-page client, read-only for users
mobile/          Capacitor wrapper + Xcode project for iOS
backend/
  collectors/    yfinance + news scraping
  analysis/      Scoring engine, Gemini integration, batch + portfolio
  main.py        REST API (public + admin behind X-Admin-Key)
scripts/         Cron jobs (weekly batch, daily market summary, iOS build)
```

The same Next.js app builds two ways:

- `npm run build` → `output: standalone`, served by Docker.
- `BUILD_TARGET=mobile npm run build` → `output: export`, bundled into the
  Capacitor iOS project.

Both call the same backend over HTTPS.

## Run locally

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env        # fill in GEMINI_API_KEY
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install && npm run dev
```

## Deploy

```bash
cp .env.example .env              # GEMINI_API_KEY, ADMIN_KEY, DOMAIN
docker compose up -d --build
```

Caddy provisions Let's Encrypt certificates automatically. The app does not run
its own scheduler — two host cron jobs drive the weekly batch and daily
market summary; see `scripts/weekly-batch.sh` and `scripts/daily-market-summary.sh`
for the exact crontab entries.

## iOS build *(in progress)*

```bash
./scripts/build-ios.sh            # static-export the frontend, sync to Xcode
open mobile/ios/App/App.xcworkspace
```

Runs in the iOS Simulator today. Device deployment and App Store submission
need full Xcode plus an Apple Developer account; native polish (push
notifications, app icon, splash, hiding `/admin` from the bundle) is still
on the to-do list.
