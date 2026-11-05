"""
Synthetic Gemini-like signals, calibrated to how Gemini actually behaved.

Historical and synthetic price paths have no real Gemini analyses, so we generate fair
values with the same statistical behaviour as the 29 weeks of live analyses:

    log FV_t = log FV_{t-1} + beta * (log P_t - log P_{t-1}) + eps_t,   eps ~ N(0, sigma)

beta  — how much Gemini's fair value follows the price (1 = fully, 0 = not at all)
sigma — week-to-week noise in fair value with no price move

Scores follow score = a + b * upside + noise, also fitted. Optionally a "skill" term
tilts upside toward the stock's actual future return so the signal has a chosen
information coefficient (IC): IC 0 means Gemini has no predictive power, which is the
honest null hypothesis for stress tests.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..analysis.strategy import Signal

FWD_WEEKS = 4


@dataclass
class Calibration:
    beta: float
    sigma: float
    score_a: float
    score_b: float
    score_sigma: float
    ic: float  # mean cross-sectional Spearman corr of upside vs next-4-round return
    ic_tstat: float
    n_obs: int
    upside0: dict[str, float]  # latest real upside per ticker (starting cross-section)
    conviction: dict[str, int]

    def describe(self) -> str:
        return (
            f"fair value follows price with beta={self.beta:.2f} (1 = moves 1:1 with price); "
            f"weekly fair-value noise sigma={self.sigma * 100:.1f}%; "
            f"score = {self.score_a:.1f} + {self.score_b:.1f} x upside (noise {self.score_sigma:.1f}); "
            f"IC upside->next {FWD_WEEKS} rounds = {self.ic:+.3f} (t={self.ic_tstat:.1f}); "
            f"{self.n_obs} weekly observations"
        )


def calibrate(analyses: pd.DataFrame) -> Calibration:
    """`analyses`: ticker, d (date str), price, fv, score, conviction — valid rows only."""
    df = analyses.dropna(subset=["price", "fv"]).copy()
    df = df[(df.price > 0) & (df.fv > 0)]
    df = df.sort_values(["ticker", "d"]).groupby(["ticker", "d"]).last().reset_index()
    df["lp"], df["lfv"] = np.log(df.price), np.log(df.fv)
    df["up"] = df.lfv - df.lp
    g = df.groupby("ticker")
    df["dlp"], df["dlfv"] = g.lp.diff(), g.lfv.diff()

    m = df.dropna(subset=["dlp", "dlfv"])
    # Winsorize so a split or a bad print doesn't dominate the fit.
    x = m.dlp.clip(m.dlp.quantile(0.01), m.dlp.quantile(0.99))
    y = m.dlfv.clip(m.dlfv.quantile(0.01), m.dlfv.quantile(0.99))
    beta = float((x * y).sum() / (x * x).sum())
    sigma = float((y - beta * x).std())

    s = df.dropna(subset=["score"])
    b, a = np.polyfit(s.up, s.score, 1)
    score_sigma = float((s.score - (a + b * s.up)).std())

    df["fwd"] = g.lp.shift(-FWD_WEEKS) - df.lp
    ics = []
    for _, cs in df.dropna(subset=["fwd"]).groupby("d"):
        if len(cs) >= 30:
            ics.append(cs.up.rank().corr(cs.fwd.rank()))
    ics = np.array(ics)
    ic = float(ics.mean()) if len(ics) else 0.0
    # Overlapping 4-week windows: deflate the t-stat by sqrt(4).
    tstat = float(ic / (ics.std(ddof=1) / np.sqrt(len(ics) / FWD_WEEKS))) if len(ics) > 2 else 0.0

    last = df.groupby("ticker").last()
    return Calibration(
        beta=beta, sigma=sigma, score_a=float(a), score_b=float(b), score_sigma=score_sigma,
        ic=ic, ic_tstat=tstat, n_obs=len(m),
        upside0=last.up.to_dict(),
        conviction={t: int(c) for t, c in last.conviction.dropna().items()},
    )


def label_for(upside: float) -> str:
    """Gemini's label boundaries as observed in the live data."""
    if upside >= 0.11:
        return "Undervalued"
    if upside <= -0.03:
        return "Overvalued"
    return "Fair Value"


# Fair-value noise with the new prompt (previous assessment as prior), from the live A/B
# test: ~0% move in quiet weeks, ~3.9% median move after earnings, and the fresh-look
# week every 4th week behaves like the old prompt. Median |x| of N(0, s) is 0.674 s.
NEW_PROMPT_NOISE = {"quiet": 0.005, "earnings": 0.039 / 0.674, "fresh": None, "fresh_every": 4, "earnings_every": 13}


def generate_rounds(
    prices: pd.DataFrame,
    cal: Calibration,
    rng: np.random.Generator,
    target_ic: float = 0.0,
    noise: str = "old",
) -> list[tuple[object, dict[str, Signal]]]:
    """Weekly price panel (index = dates, columns = tickers) -> strategy rounds with signals.

    noise="old": every week gets the calibrated old-prompt noise (sigma).
    noise="new": quiet weeks, earnings jumps once a quarter per stock, and an old-prompt-sized
                 re-estimate on every 4th (fresh-look) week."""
    tickers = list(prices.columns)
    lp = np.log(prices.to_numpy(dtype=float))
    n_weeks, n = lp.shape

    up_pool = np.array(list(cal.upside0.values())) if cal.upside0 else np.array([0.1])
    u0 = np.array([cal.upside0.get(t, rng.choice(up_pool)) for t in tickers])
    lfv = np.empty_like(lp)
    lfv[0] = lp[0] + u0
    if noise == "new":
        nz = NEW_PROMPT_NOISE
        sd = np.full((n_weeks, n), nz["quiet"])
        phase = rng.integers(0, nz["earnings_every"], size=n)
        weeks = np.arange(n_weeks)[:, None]
        sd = np.where((weeks - phase) % nz["earnings_every"] == 0, nz["earnings"], sd)
        sd[np.arange(n_weeks) % nz["fresh_every"] == nz["fresh_every"] - 1] = nz["fresh"] or cal.sigma
        eps = rng.normal(0, 1, size=(n_weeks, n)) * sd
    else:
        eps = rng.normal(0, cal.sigma, size=(n_weeks, n))
    for w in range(1, n_weeks):
        dlp = np.nan_to_num(lp[w] - lp[w - 1])
        lfv[w] = lfv[w - 1] + cal.beta * dlp + eps[w]
    up = np.clip(lfv - lp, -0.7, 1.2)

    if target_ic > 0:
        fwd = np.full_like(lp, np.nan)
        fwd[:-FWD_WEEKS] = lp[FWD_WEEKS:] - lp[:-FWD_WEEKS]
        # Blend a standardized future-return term into upside until rank IC ~= target.
        z = (fwd - np.nanmean(fwd, axis=1, keepdims=True)) / (np.nanstd(fwd, axis=1, keepdims=True) + 1e-9)
        noise_sd = np.nanstd(up, axis=1, keepdims=True)
        k = _solve_skill(up, z, noise_sd, target_ic)
        up = np.where(np.isnan(z), up, up + k * noise_sd * z)

    score = np.clip(cal.score_a + cal.score_b * up + rng.normal(0, cal.score_sigma, up.shape), 0, 100)

    rounds = []
    for w, d in enumerate(prices.index):
        sigs = {}
        for i, t in enumerate(tickers):
            if np.isnan(lp[w, i]):
                continue
            p = float(np.exp(lp[w, i]))
            fv = float(p * np.exp(up[w, i]))
            sigs[t] = Signal(t, p, fv, label_for(fv / p - 1), float(score[w, i]), cal.conviction.get(t, 7))
        rounds.append((pd.Timestamp(d).date(), sigs))
    return rounds


def _solve_skill(up, z, noise_sd, target_ic, iters=20) -> float:
    def ic_for(k):
        blended = up + k * noise_sd * z
        vals = []
        for w in range(0, up.shape[0], 4):
            mask = ~np.isnan(z[w]) & ~np.isnan(blended[w])
            if mask.sum() > 20:
                vals.append(pd.Series(blended[w][mask]).rank().corr(pd.Series(z[w][mask]).rank()))
        return np.mean(vals) if vals else 0.0

    lo, hi = 0.0, 2.0
    for _ in range(iters):
        mid = (lo + hi) / 2
        if ic_for(mid) < target_ic:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2
