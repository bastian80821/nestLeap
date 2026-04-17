"""Collect recent news for a stock from yfinance and RSS feeds."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import yfinance as yf


@dataclass
class NewsItem:
    title: str
    source: str
    published: Optional[str] = None
    url: Optional[str] = None


def get_stock_news(ticker: str, max_items: int = 8) -> list[NewsItem]:
    """Get recent news headlines for a ticker via yfinance."""
    items: list[NewsItem] = []
    try:
        t = yf.Ticker(ticker)
        news = t.news
        if not news:
            return items

        for article in news[:max_items]:
            content = article.get("content", article)
            title = (
                content.get("title")
                or article.get("title")
                or ""
            )
            if not title:
                continue

            provider = content.get("provider", {})
            source = (
                provider.get("displayName")
                if isinstance(provider, dict)
                else article.get("publisher", "Unknown")
            )
            pub_date = content.get("pubDate") or article.get("providerPublishTime")
            if isinstance(pub_date, (int, float)):
                pub_date = datetime.fromtimestamp(pub_date).isoformat()

            url = (
                content.get("canonicalUrl", {}).get("url")
                if isinstance(content.get("canonicalUrl"), dict)
                else article.get("link")
            )

            items.append(NewsItem(
                title=title,
                source=source or "Unknown",
                published=str(pub_date) if pub_date else None,
                url=url,
            ))
    except Exception:
        pass

    return items
