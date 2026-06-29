"""News fetching via yfinance, adapted from TradingAgents."""

import contextlib
import time
import logging
from datetime import datetime
from dateutil.relativedelta import relativedelta

import yfinance as yf
from yfinance.exceptions import YFRateLimitError
from fastapi import APIRouter

router = APIRouter()
log = logging.getLogger(__name__)

_ARTICLE_LIMIT = 30


def _yf_retry(func, max_retries=3, base_delay=2.0):
    for attempt in range(max_retries + 1):
        try:
            return func()
        except YFRateLimitError:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)
            else:
                raise


def _extract_article(article: dict) -> dict:
    if "content" in article:
        content = article["content"]
        provider = content.get("provider", {})
        url_obj = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
        pub_date = None
        pub_date_str = content.get("pubDate", "")
        if pub_date_str:
            with contextlib.suppress(ValueError, AttributeError):
                pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00")).replace(tzinfo=None)
        return {
            "title": content.get("title", ""),
            "summary": content.get("summary", ""),
            "publisher": provider.get("displayName", ""),
            "link": url_obj.get("url", ""),
            "pub_date": pub_date.isoformat() if pub_date else None,
        }
    else:
        pub_date = None
        ts = article.get("providerPublishTime")
        if ts:
            with contextlib.suppress(ValueError, OSError, TypeError):
                pub_date = datetime.fromtimestamp(ts)
        return {
            "title": article.get("title", ""),
            "summary": article.get("summary", ""),
            "publisher": article.get("publisher", ""),
            "link": article.get("link", ""),
            "pub_date": pub_date.isoformat() if pub_date else None,
        }


@router.get("/news/{ticker}")
def news_endpoint(ticker: str, days: int = 30):
    ticker = ticker.upper()
    end_dt = datetime.now()
    start_dt = end_dt - relativedelta(days=days)

    try:
        stock = yf.Ticker(ticker)
        raw = _yf_retry(lambda: stock.get_news(count=_ARTICLE_LIMIT)) or []
    except Exception as e:
        log.warning("yfinance news fetch failed for %s: %s", ticker, e)
        return []

    articles = []
    for item in raw:
        art = _extract_article(item)
        if not art["title"]:
            continue
        # date filter — undated articles only included for live (recent) windows
        if art["pub_date"]:
            pub = datetime.fromisoformat(art["pub_date"])
            if not (start_dt <= pub <= end_dt + relativedelta(days=1)):
                continue
        articles.append(art)

    return articles
