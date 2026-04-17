# NestLeap

Stock analysis platform for long-term investors. Analyzes ~200 large-cap stocks weekly using fundamentals data from Yahoo Finance and AI-generated insights via Google Gemini. Runs a simulated DCA portfolio that buys the top undervalued picks and benchmarks against the S&P 500.

## What it does

- **Weekly batch analysis** of the top 200 US stocks by market cap
- **Deterministic scoring** across quality, value, growth, and momentum metrics
- **AI synthesis** via Gemini — generates fair value estimates, risk/catalyst assessment, and an overall score that adjusts the deterministic baseline
- **Daily market summary** with index data and news context
- **Simulated portfolio** — $1,000/week DCA into the top 10 undervalued stocks, sells positions at fair value or overvalued, tracks performance vs S&P 500
- **Admin panel** at `/admin` for triggering batch runs, rebalancing, and individual stock analysis

## Architecture

```
frontend/          Next.js 14, Tailwind CSS, single-page app
backend/           FastAPI, SQLAlchemy, SQLite
  app/
    collectors/    Yahoo Finance data + news
    analysis/      Scoring engine, Gemini integration, batch runner, portfolio engine
    main.py        API endpoints (public + admin)
```

The backend collects fundamentals via `yfinance`, computes deterministic sub-scores (16 metrics), then makes a single Gemini API call per stock to synthesize everything into a valuation, fair value estimate, and adjusted overall score. Results are stored in SQLite.

The frontend is read-only for users. All write operations (batch analysis, re-analysis, rebalance) require an admin key passed via `X-Admin-Key` header.

## Running locally

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example ../.env  # edit with your Gemini key
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

## Deploying

The project ships with Docker Compose + Caddy for deployment on any VPS.

```bash
cp .env.example .env   # fill in GEMINI_API_KEY, ADMIN_KEY, DOMAIN
docker compose up -d --build
```

Caddy handles HTTPS automatically via Let's Encrypt. Set up a weekly cron for batch analysis:

```
0 2 * * 0 cd /path/to/stock_platform && ./scripts/weekly-batch.sh
```

See `.env.example` for required environment variables.
