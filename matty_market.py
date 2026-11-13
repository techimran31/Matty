"""
matty_market.py - Real-time market data and Buy/Sell signals.

READING GUIDE
-------------
    analyze_ticker("RELIANCE.NS")   <- one stock, full verdict
        STEP 1  download 5 days of 15 minute candles from Yahoo Finance
        STEP 2  read price, previous close and currency
        STEP 3  compute the % change since the previous close
        STEP 4  compute a short (5 candle) and a medium (15 candle) average
        STEP 5  compare price vs. those averages -> BUY / SELL / HOLD
        STEP 6  return one dict that the voice layer turns into a sentence

    market_briefing()   -> spoken overview of the main indices
    get_market_watchlist() -> structured data for the HUD ticker panel

No API key is required: Yahoo's public chart endpoint is used directly.
"""

import urllib.request
import urllib.parse
import json
import ssl
import time

try:
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _CTX = None

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"

# Default Watchlist: Indian Bluechips, Indices, US Tech & Crypto
DEFAULT_TICKERS = {
    "^NSEI": "Nifty 50",
    "^BSESN": "Sensex",
    "RELIANCE.NS": "Reliance Industries",
    "TCS.NS": "TCS",
    "INFY.NS": "Infosys",
    "HDFCBANK.NS": "HDFC Bank",
    "NVDA": "Nvidia",
    "AAPL": "Apple",
    "BTC-USD": "Bitcoin",
}


def _fetch_chart(symbol, range_period="5d", interval="15m"):
    """Download the raw candle data for one symbol.

    STEP 1  Build the Yahoo Finance chart URL (symbol is URL-encoded, so
            ^NSEI or BTC-USD are safe).
    STEP 2  Send a normal browser User-Agent - Yahoo rejects the default one.
    STEP 3  Parse the JSON and dig down to chart.result[0].
    STEP 4  Return None on any problem (offline, delisted symbol, HTML error
            page) so the caller can say "no data" instead of crashing.
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range={range_period}&interval={interval}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10, context=_CTX) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore"))
            res = data.get("chart", {}).get("result", [])
            if not res:
                return None
            return res[0]
    except Exception as e:
        return None


def analyze_ticker(symbol):
    """Return price, momentum and a Buy/Sell/Hold verdict for one symbol.

    STEP 1  Fetch the candles; give up quietly when there is no data.
    STEP 2  Read the metadata: friendly name, currency, live price, prev close.
    STEP 3  Compute absolute change and % change.
    STEP 4  Pull the close prices and drop empty candles (market holidays).
    STEP 5  With at least 10 closes, compare price against the 5 and 15 candle
            averages to pick a signal; otherwise stay neutral (HOLD).
    STEP 6  Return a dict - the caller decides how to phrase it.
    """
    chart = _fetch_chart(symbol)
    if not chart:
        return None

    meta = chart.get("meta", {})
    name = DEFAULT_TICKERS.get(symbol, symbol)
    currency = meta.get("currency", "INR" if ".NS" in symbol or "^" in symbol else "USD")
    curr_symbol = "₹" if currency == "INR" else "$"

    price = meta.get("regularMarketPrice")
    prev_close = meta.get("chartPreviousClose") or meta.get("previousClose") or price

    if price is None:
        return None

    change = price - prev_close
    pct_change = (change / prev_close) * 100 if prev_close else 0.0

    quotes = chart.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    valid_quotes = [q for q in quotes if q is not None]

    # STEP 5 - trend logic. sma_short = last 5 closes, sma_long = last 15.
    # The four cases are ordered from strongest bull to strongest bear.
    signal = "HOLD"
    reason = "Consolidating near previous close."

    if len(valid_quotes) >= 10:
        sma_short = sum(valid_quotes[-5:]) / 5.0
        sma_long = sum(valid_quotes[-15:]) / min(len(valid_quotes), 15)

        if price > sma_short and sma_short > sma_long and pct_change > 0.5:
            signal = "STRONG BUY"
            reason = "Bullish momentum above short-term and medium-term moving averages."
        elif price > sma_short and pct_change >= 0.0:
            signal = "BUY / ACCUMULATE"
            reason = "Holding above short-term support with positive price action."
        elif price < sma_short and sma_short < sma_long and pct_change < -0.5:
            signal = "STRONG SELL / SHORT"
            reason = "Bearish crossover below major moving averages with active selling pressure."
        elif price < sma_short:
            signal = "SELL / TAKE PROFIT"
            reason = "Slipping below intraday support; risk of further pullback."

    return {
        "symbol": symbol,
        "name": name,
        "price": round(price, 2),
        "change": round(change, 2),
        "pct_change": round(pct_change, 2),
        "currency": curr_symbol,
        "signal": signal,
        "reason": reason,
        "high": meta.get("regularMarketDayHigh", price),
        "low": meta.get("regularMarketDayLow", price),
    }


def market_briefing():
    """Spoken overview: index + one Indian stock + one US stock + crypto.

    Kept short on purpose - this text is read aloud, so four lines is about
    the limit before it stops feeling like an executive briefing.
    """
    reports = []
    for sym in ["^NSEI", "RELIANCE.NS", "NVDA", "BTC-USD"]:
        data = analyze_ticker(sym)
        if data:
            direction = "up" if data["pct_change"] >= 0 else "down"
            reports.append(
                f"{data['name']} is at {data['currency']}{data['price']:,}, {direction} {abs(data['pct_change'])}%. Signal: {data['signal']}."
            )
    return " ".join(reports)


def get_market_watchlist():
    """Returns all watched tickers as structured data for the holographic HUD."""
    results = []
    for sym, name in DEFAULT_TICKERS.items():
        data = analyze_ticker(sym)
        if data:
            results.append(data)
    return results


if __name__ == "__main__":
    print("Testing Matty Market Intelligence...")
    print(market_briefing())
