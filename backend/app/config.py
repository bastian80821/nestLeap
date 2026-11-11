from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    gemini_fallback_model: str = "gemini-3-flash-preview"
    database_url: str = "sqlite:///./nestleap.db"
    admin_key: str = "changeme"
    # Portfolio rules preset from analysis/strategy.py: "v2" or "legacy"
    portfolio_strategy: str = "v2"

    # ── Broker trading (see docs/ROLLOUT.md) ────────────────────────────────
    trading_mode: str = "off"  # off | paper | live
    trading_broker: str = "sim"  # sim (simulated fills at market prices) | ibkr
    trading_approval: str = "manual"  # manual: you approve each week | auto
    # Money model: you deposit into a pool (in trading_currency, e.g. EUR 5,000). Each week the
    # strategy may draw at most trading_weekly_new_money from the pool for new buys; unused
    # allowance stays in the pool (it does not accumulate). Sale proceeds are kept separately
    # and the strategy re-buys with them or holds them as cash.
    trading_currency: str = "EUR"
    trading_weekly_new_money: float = 400.0
    trading_max_buys_per_week: int = 2
    # Bug guards in USD (independent of the allowance): buys are clipped to these.
    trading_max_order_value: float = 2000.0
    trading_max_weekly_buys: float = 4000.0
    # Convert the pool currency to USD automatically when buys need it, in chunks of at
    # least this much (IBKR charges ~USD 2 per conversion).
    trading_auto_fx: bool = True
    trading_fx_min_conversion: float = 1000.0
    # Price moves between proposal and submission: up to `tolerance` the order goes out as
    # proposed; up to `max_price_move` it is re-checked against the fair value at the live
    # price (buys must still be cheap enough, sells still in the sell zone); beyond, skipped.
    trading_price_tolerance: float = 0.03
    trading_max_price_move: float = 0.10
    trading_limit_offset: float = 0.005  # limit = price +0.5% for buys, -0.5% for sells
    trading_fractional: bool = True  # broker accepts fractional-share orders
    trading_sim_state: str = "/app/data/sim_broker.json"
    ib_host: str = "ib-gateway"
    ib_port: int = 4004  # gnzsnz/ib-gateway relays paper on 4004, live on 4003
    ib_client_id: int = 17
    ib_account: str = ""  # optional; defaults to the gateway's only account
    # Optional: IBKR Flex Web Service for the independent monthly statement audit
    ib_flex_token: str = ""
    ib_flex_query_id: str = ""
    # Optional push notifications: any ntfy-compatible URL, e.g. https://ntfy.sh/<secret-topic>
    notify_url: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
