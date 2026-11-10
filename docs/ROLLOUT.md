# Broker trading rollout

Four stages. Each has a gate: don't move on until every item in it is true.
Nothing below risks real money until stage 2, and stage 2 starts only when you
change `TRADING_MODE=live` yourself.

| Stage | Broker | Money | Approval | Purpose |
|---|---|---|---|---|
| 0 | `sim` (simulated fills) | simulated EUR 5,000 | manual | Prove the weekly pipeline and audits on the server |
| 1 | IBKR paper account | paper EUR 5,000 | auto | Prove the IBKR integration, FX and real fills |
| 2 | IBKR live account | real EUR 5,000 | manual | First real money, you approve each week |
| 3 | IBKR live account | real | auto | Hands-off |

## Money model

- You deposit into a **pool** (EUR 5,000) and record it once: `trading.sh deposit 5000`.
- Each week the strategy may draw **at most EUR 400** of new money from the pool, for **at most 2 buys**.
  Unused allowance stays in the pool: it never accumulates into a bigger week.
- **Sale proceeds** go to a separate bucket. The strategy re-buys with them (on top of the EUR 400)
  or holds them as cash, e.g. while SPY is below its 200-day average. Buys spend proceeds first.
- EUR is converted to USD automatically when buys need it, at least EUR 1,000 at a time (IBKR charges
  about USD 2 per conversion).
- At EUR 400/week the pool lasts ~12.5 weeks. Two weeks before it runs out you get a notification;
  deposit more and record it with `trading.sh deposit <amount>`, or let the system continue on sale
  proceeds alone. Any other cash in the account is never touched.

## How a week works

| When (UTC) | What | Command |
|---|---|---|
| Sun 02:00 | Batch analysis, website portfolio rebalance, market summary, **propose** broker trades | `weekly-batch.sh` → `trading.sh propose` |
| Sun–Mon | **Approve** (manual stages): admin page → Broker trading → Approve week | or `trading.sh approve <run>` |
| Mon–Fri 15:00–18:30 | **Submit** approved orders: sells first, then FX if needed, then buys, as limit orders on NYSE trading days | `trading.sh submit` |
| Mon–Fri during market | **Sync** fills; 19:45 cancel anything unfilled | `trading.sh sync [--eod]` |
| Mon–Fri 22:00 | **Reconcile** positions, executions and cash | `trading.sh reconcile` |
| Fri 22:30 | **Weekly audit** | `trading.sh audit` |
| 2nd of month | **Statement audit** against IBKR's own records | `trading.sh audit-statement` |

## Audit strategy

Three independent layers. Any critical failure engages the kill switch and notifies you.

**1. Continuous safeguards (prevent).** Kill switch; paper/live lock; EUR 400/week new-money cap and
2-buy cap enforced at proposal *and* re-checked at submission; per-order and weekly USD caps; universe
whitelist; price-moved check (±3%); limit orders only; NYSE calendar; stale/incomplete data skipped.

**2. Daily reconciliation (detect quickly).** Broker positions must equal recorded fills; every
execution in the account must be a NestLeap order (a manual trade halts trading until you review it
and run `trading.sh adopt-baseline`); account cash must match pool + proceeds (warning on small FX
drift, halt if more than 5% is missing).

**3. Weekly audit (verify everything).** A report of 13 checks, stored and shown in the admin page:

| Check | Verifies | Severity |
|---|---|---|
| event_chain | every audit-log row is unmodified (SHA-256 hash chain) | critical |
| order_history | each order's state matches its last logged event | critical |
| decision_replay | recomputing the strategy from the stored inputs gives exactly the recorded orders | critical |
| approvals | nothing reached the broker without an approval | critical |
| new_money_cap | new money drawn ≤ EUR 400 (and ≤ the pool) | critical |
| max_buys | ≤ 2 buy orders | critical |
| limit_prices | every fill respected its limit | critical |
| ledger_integrity | every fill fully booked; pool and proceeds never negative | critical |
| universe | only analysed stocks held | critical |
| positions | broker positions = recorded fills | critical |
| foreign_trades | no executions NestLeap didn't place | critical |
| cash | account cash = pool + proceeds | warning |
| fees | commissions in line with IBKR pricing | warning |

It also reports performance: value in EUR vs deposits, against **SPY bought with exactly the same new
money on the same days** (and charged the same FX fees), plus fees paid.

**4. Monthly statement audit (independent source).** Pulls IBKR's back-office activity statement via
the Flex Web Service, outside the trading API, and checks both directions: every NestLeap fill appears
with the same quantity, price and commission, and the statement contains no other trades. Setup (once):
Client Portal → Performance & Reports → Flex Queries → create an Activity query (XML) with the *Trades*
section (include *Order Reference*) and the *Cash Transactions* section (dividends and withholding tax,
used by the tax report), note the Query ID; Flex Web Service → generate a token. Put both in
`.env` as `IB_FLEX_QUERY_ID` / `IB_FLEX_TOKEN`.

**Tamper evidence.** Each audit notification includes the event-chain head hash. Because the
notification leaves the server, a later rewrite of the history (even one that recomputes the chain)
no longer matches the hash on your phone.

## Taxes (Germany)

IBKR withholds no German tax and issues no Steuerbescheinigung: you declare everything in Anlage KAP
(shares, dividends) and Anlage SO (USD currency results, § 23 EStG). NestLeap prepares the worksheet:

```bash
./scripts/trading.sh tax-report 2026                              # from NestLeap's records (no dividends)
./scripts/trading.sh tax-report 2026 --statement - < 2026.xml     # plus dividends/withholding from IBKR
```

Download the year's statement in Client Portal: run the Flex query for 1 Jan – 31 Dec and save the XML.
The command prints the Anlage KAP/SO figures and writes per-trade CSVs (FIFO lots, EUR at ECB reference
rates, currency lots with holding periods) to `/app/data/tax/<year>-<mode>/` for you or your Steuerberater.
The admin page shows the same summary (without dividends). Not tax advice; check form line numbers on the
current year's Vordruck.

## Stage 0 — simulated broker (can start now)

`.env` on the server: `TRADING_MODE=paper`, `TRADING_BROKER=sim`, `TRADING_APPROVAL=manual`,
optionally `NOTIFY_URL=https://ntfy.sh/<long-random-topic>`. Then:

```bash
./scripts/deploy.sh
crontab scripts/crontab.txt        # scripts read ADMIN_KEY from .env
./scripts/trading.sh deposit 5000  # simulated EUR 5,000
```

**Gate to stage 1** (2+ weeks): proposals arrive every Sunday; approving works; orders fill Monday;
FX conversion happens once per ~EUR 1,000; reconcile passes every weekday; weekly audits pass.

## Stage 1 — IBKR paper account

You: open an IBKR Pro account (base currency EUR is fine), enable US stocks **and fractional shares**
(Settings → Account Settings → Trading Permissions), and note the **paper trading** username and
password (Settings → Paper Trading Account). Set up the Flex query and token (above) for the paper account.

`.env`: `TRADING_BROKER=ibkr`, `IB_USERNAME`/`IB_PASSWORD` = paper login, `IB_GATEWAY_MODE=paper`,
`IB_PORT=4004`, `TRADING_APPROVAL=auto`, `IB_FLEX_TOKEN`/`IB_FLEX_QUERY_ID`. Then:

```bash
./scripts/deploy.sh                 # starts ib-gateway too (profile ibkr)
./scripts/trading.sh check          # account must start with DU; fractional what-if must be accepted
./scripts/trading.sh archive paper-sim   # file the stage-0 simulated records separately
./scripts/trading.sh deposit 5000   # the paper account's EUR (record what the strategy may use)
./scripts/trading.sh adopt-baseline # only if the paper account already holds positions
```

**Gate to stage 2** (4–8 weeks): every week filled without manual help; FX conversions filled;
fills within ~0.5% of proposal prices; commissions match; reconcile, weekly and statement audits all
pass; the gateway stays logged in across its nightly restart.

## Stage 2 — live, manual approval

You: fund the live account with EUR 5,000 and set up IBKR Mobile for two-factor login (the gateway
asks for a 2FA approval on your phone about once a week; if you miss it, trading pauses until you log in).
Create the Flex query/token for the live account.

`.env`: `TRADING_MODE=live`, live `IB_USERNAME`/`IB_PASSWORD`, `IB_GATEWAY_MODE=live`, `IB_PORT=4003`,
`TRADING_APPROVAL=manual`, live Flex token/query. Deploy, `trading.sh check` (account must **not** start
with DU), then `trading.sh deposit 5000`. Each Sunday: review the proposal, approve or reject.

**Gate to stage 3** (8+ weeks): you approved every week without wanting to change anything;
every audit passed; no safeguard fired unexpectedly.

## Stage 3 — live, automatic

`.env`: `TRADING_APPROVAL=auto`, redeploy. From then on only the deposits are yours: top up the pool
when notified and record it with `trading.sh deposit <amount>`.

## Rolling back

- Stop all trading now: admin page → Halt trading (or `trading.sh kill on --reason "..."`).
- Back to simulation: `TRADING_MODE=paper`, `TRADING_BROKER=sim`, redeploy.
- Old portfolio rules for the website: `PORTFOLIO_STRATEGY=legacy`.
- Code: `git checkout <previous commit> && docker compose up -d --build`; database backups are in `/root/backups`.
