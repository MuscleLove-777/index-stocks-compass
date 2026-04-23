"""Index Stocks Compass — データ取得＋HTML生成ワンショット更新スクリプト。

手順:
    1. Wikipedia から5指数の構成銘柄リストを取得
    2. yfinance で全銘柄の現在値・前日比・時価総額・セクターを一括取得
    3. data/*.json に保存
    4. テンプレートで各指数ページとトップページのHTMLを生成
    5. sitemap.xml を更新
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

WIKI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}

# stdout UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
TODAY = NOW.strftime("%Y-%m-%d")

BASE_URL = "https://musclelove-777.github.io/index-stocks-compass"

# ======================================================================
# Index definitions
# ======================================================================
INDICES = {
    # ========== 日本 ==========
    "n225": {
        "name_ja": "日経平均株価 (Nikkei 225)", "name_en": "Nikkei 225", "symbol": "^N225",
        "wiki_url": "https://topforeignstocks.com/indices/the-components-of-the-nikkei-225-index/",
        "ticker_col_candidates": ["Code", "Symbol", "Ticker", "コード"],
        "name_col_candidates": ["Company Name", "Company", "Name", "銘柄名"],
        "sector_col_candidates": ["Sector", "Industry", "業種"],
        "market": "JP", "ticker_suffix": ".T", "digits_only": True, "digits_length": 4,
        "country": "Japan", "region": "Japan", "flag": "🇯🇵",
        "desc": "日本の代表的な225銘柄で構成される株価平均型指数。東証プライム市場から選定。",
    },
    "topix-core30": {
        "name_ja": "TOPIX Core30", "name_en": "TOPIX Core30", "symbol": "^TPX",
        "wiki_url": "https://ja.wikipedia.org/wiki/TOPIX_Core_30",
        "ticker_col_candidates": ["銘柄コード", "コード", "証券コード", "Code"],
        "name_col_candidates": ["銘柄名", "企業名", "社名", "名称", "Company"],
        "sector_col_candidates": ["業種", "セクター", "Sector"],
        "market": "JP", "ticker_suffix": ".T", "digits_only": True, "digits_length": 4,
        "country": "Japan", "region": "Japan", "flag": "🇯🇵",
        "desc": "TOPIX構成銘柄のうち時価総額・流動性最上位の30銘柄で構成される指数。",
    },
    # ========== アメリカ ==========
    "sp500": {
        "name_ja": "S&P 500", "name_en": "S&P 500", "symbol": "^GSPC",
        "wiki_url": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "ticker_col_candidates": ["Symbol", "Ticker symbol"],
        "name_col_candidates": ["Security", "Company"],
        "sector_col_candidates": ["GICS Sector", "Sector"],
        "market": "US", "ticker_suffix": "", "digits_only": False,
        "country": "United States", "region": "Americas", "flag": "🇺🇸",
        "desc": "米国を代表する大型株500銘柄で構成される時価総額加重平均指数。",
    },
    "nasdaq100": {
        "name_ja": "NASDAQ-100", "name_en": "NASDAQ-100", "symbol": "^NDX",
        "wiki_url": "https://en.wikipedia.org/wiki/Nasdaq-100",
        "ticker_col_candidates": ["Ticker", "Symbol"],
        "name_col_candidates": ["Company", "Security"],
        "sector_col_candidates": ["GICS Sector", "Sector"],
        "market": "US", "ticker_suffix": "", "digits_only": False,
        "country": "United States", "region": "Americas", "flag": "🇺🇸",
        "desc": "NASDAQ上場の金融を除く時価総額上位100銘柄で構成される指数。",
    },
    "dow30": {
        "name_ja": "NYダウ (Dow Jones Industrial Average)", "name_en": "Dow Jones Industrial Average", "symbol": "^DJI",
        "wiki_url": "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average",
        "ticker_col_candidates": ["Symbol", "Ticker"],
        "name_col_candidates": ["Company", "Security"],
        "sector_col_candidates": ["Industry", "GICS Sector", "Sector"],
        "market": "US", "ticker_suffix": "", "digits_only": False,
        "country": "United States", "region": "Americas", "flag": "🇺🇸",
        "desc": "米国を代表する30の優良企業で構成される価格加重平均指数。",
    },
    # ========== 欧州 ==========
    "ftse100": {
        "name_ja": "FTSE 100", "name_en": "FTSE 100", "symbol": "^FTSE",
        "wiki_url": "https://en.wikipedia.org/wiki/FTSE_100_Index",
        "ticker_col_candidates": ["EPIC", "Ticker", "Symbol", "Code"],
        "name_col_candidates": ["Company", "Name"],
        "sector_col_candidates": ["FTSE Industry Classification Benchmark sector", "FTSE Industry Classification Benchmark", "Sector", "Industry"],
        "market": "UK", "ticker_suffix": ".L", "digits_only": False,
        "country": "United Kingdom", "region": "Europe", "flag": "🇬🇧",
        "desc": "ロンドン証券取引所(LSE)上場の時価総額上位100銘柄で構成されるイギリス代表指数。",
    },
    "dax40": {
        "name_ja": "DAX 40", "name_en": "DAX", "symbol": "^GDAXI",
        "wiki_url": "https://en.wikipedia.org/wiki/DAX",
        "ticker_col_candidates": ["Ticker symbol", "Ticker", "Symbol"],
        "name_col_candidates": ["Company", "Name"],
        "sector_col_candidates": ["Prime Standard Sector", "Industry", "Sector"],
        "market": "DE", "ticker_suffix": ".DE", "digits_only": False,
        "country": "Germany", "region": "Europe", "flag": "🇩🇪",
        "desc": "フランクフルト証券取引所に上場するドイツ主要40銘柄で構成される指数。",
    },
    "cac40": {
        "name_ja": "CAC 40", "name_en": "CAC 40", "symbol": "^FCHI",
        "wiki_url": "https://en.wikipedia.org/wiki/CAC_40",
        "ticker_col_candidates": ["Ticker", "Symbol", "EURONEXT"],
        "name_col_candidates": ["Company", "Name"],
        "sector_col_candidates": ["Sector", "Industry"],
        "market": "FR", "ticker_suffix": ".PA", "digits_only": False,
        "country": "France", "region": "Europe", "flag": "🇫🇷",
        "desc": "ユーロネクスト・パリに上場するフランス主要40銘柄で構成される指数。",
    },
    "ftsemib": {
        "name_ja": "FTSE MIB", "name_en": "FTSE MIB", "symbol": "FTSEMIB.MI",
        "wiki_url": "https://en.wikipedia.org/wiki/FTSE_MIB",
        "ticker_col_candidates": ["Ticker", "Symbol", "Code", "ISIN"],
        "name_col_candidates": ["Company", "Name"],
        "sector_col_candidates": ["ICB Sector", "Sector", "Industry"],
        "market": "IT", "ticker_suffix": ".MI", "digits_only": False,
        "country": "Italy", "region": "Europe", "flag": "🇮🇹",
        "desc": "ボルサ・イタリアーナに上場するイタリア主要40銘柄で構成される指数。",
    },
    "ibex35": {
        "name_ja": "IBEX 35", "name_en": "IBEX 35", "symbol": "^IBEX",
        "wiki_url": "https://en.wikipedia.org/wiki/IBEX_35",
        "ticker_col_candidates": ["Ticker", "Symbol", "Code"],
        "name_col_candidates": ["Company", "Name"],
        "sector_col_candidates": ["Sector", "Industry"],
        "market": "ES", "ticker_suffix": ".MC", "digits_only": False,
        "country": "Spain", "region": "Europe", "flag": "🇪🇸",
        "desc": "マドリード証券取引所に上場するスペイン主要35銘柄で構成される指数。",
    },
    "aex": {
        "name_ja": "AEX", "name_en": "AEX index", "symbol": "^AEX",
        "wiki_url": "https://en.wikipedia.org/wiki/AEX_index",
        "ticker_col_candidates": ["Ticker", "Symbol", "Code"],
        "name_col_candidates": ["Company", "Name"],
        "sector_col_candidates": ["ICB Sector", "Sector", "Industry"],
        "market": "NL", "ticker_suffix": ".AS", "digits_only": False,
        "country": "Netherlands", "region": "Europe", "flag": "🇳🇱",
        "desc": "ユーロネクスト・アムステルダムに上場するオランダ主要25銘柄で構成される指数。",
    },
    "smi": {
        "name_ja": "SMI (Swiss Market Index)", "name_en": "Swiss Market Index", "symbol": "^SSMI",
        "wiki_url": "https://en.wikipedia.org/wiki/Swiss_Market_Index",
        "ticker_col_candidates": ["Ticker", "Symbol", "ISIN"],
        "name_col_candidates": ["Company", "Name"],
        "sector_col_candidates": ["Sector", "Industry"],
        "market": "CH", "ticker_suffix": ".SW", "digits_only": False,
        "country": "Switzerland", "region": "Europe", "flag": "🇨🇭",
        "desc": "SIXスイス証券取引所に上場するスイス主要20銘柄で構成される指数。",
    },
    # ========== アジア太平洋 ==========
    "hsi": {
        "name_ja": "ハンセン指数 (Hang Seng)", "name_en": "Hang Seng Index", "symbol": "^HSI",
        "wiki_url": "https://en.wikipedia.org/wiki/Hang_Seng_Index",
        "ticker_col_candidates": ["Stock code", "Ticker", "Code", "Symbol"],
        "name_col_candidates": ["Company", "Name"],
        "sector_col_candidates": ["Industry", "Sector"],
        "market": "HK", "ticker_suffix": ".HK", "digits_only": True, "digits_length": 4,
        "country": "Hong Kong", "region": "Asia-Pacific", "flag": "🇭🇰",
        "desc": "香港証券取引所に上場する香港代表企業で構成される時価総額加重指数。",
    },
    "hstech": {
        "name_ja": "ハンセンTECH指数", "name_en": "Hang Seng TECH Index", "symbol": "^HSTECH",
        "wiki_url": "https://en.wikipedia.org/wiki/Hang_Seng_TECH_Index",
        "ticker_col_candidates": ["Stock code", "Ticker", "Code", "Symbol"],
        "name_col_candidates": ["Company", "Name"],
        "sector_col_candidates": ["Industry", "Sector"],
        "market": "HK", "ticker_suffix": ".HK", "digits_only": True, "digits_length": 4,
        "country": "Hong Kong", "region": "Asia-Pacific", "flag": "🇭🇰",
        "desc": "香港上場のテック系30銘柄で構成される、アジア版NASDAQと称される指数。",
    },
    "kospi200": {
        "name_ja": "KOSPI 200", "name_en": "KOSPI 200", "symbol": "^KS200",
        "wiki_url": "https://en.wikipedia.org/wiki/KOSPI",
        "ticker_col_candidates": ["Code", "Ticker", "Symbol"],
        "name_col_candidates": ["Company", "Name"],
        "sector_col_candidates": ["Sector", "Industry"],
        "market": "KR", "ticker_suffix": ".KS", "digits_only": True, "digits_length": 6,
        "country": "South Korea", "region": "Asia-Pacific", "flag": "🇰🇷",
        "desc": "韓国取引所(KRX)に上場する韓国主要200銘柄で構成される時価総額加重指数。",
    },
    "asx200": {
        "name_ja": "S&P/ASX 200", "name_en": "S&P/ASX 200", "symbol": "^AXJO",
        "wiki_url": "https://en.wikipedia.org/wiki/S%26P/ASX_200",
        "ticker_col_candidates": ["Code", "Ticker", "Symbol", "ASX code"],
        "name_col_candidates": ["Company", "Name"],
        "sector_col_candidates": ["GICS Sector", "Sector", "Industry"],
        "market": "AU", "ticker_suffix": ".AX", "digits_only": False,
        "country": "Australia", "region": "Asia-Pacific", "flag": "🇦🇺",
        "desc": "オーストラリア証券取引所(ASX)に上場する時価総額上位200銘柄で構成される指数。",
    },
    "nifty50": {
        "name_ja": "NIFTY 50", "name_en": "NIFTY 50", "symbol": "^NSEI",
        "wiki_url": "https://en.wikipedia.org/wiki/NIFTY_50",
        "ticker_col_candidates": ["Symbol", "Ticker", "NSE Code", "Code"],
        "name_col_candidates": ["Company name", "Company", "Name"],
        "sector_col_candidates": ["Sector", "Industry"],
        "market": "IN", "ticker_suffix": ".NS", "digits_only": False,
        "country": "India", "region": "Asia-Pacific", "flag": "🇮🇳",
        "desc": "インド国立証券取引所(NSE)に上場するインド主要50銘柄で構成される指数。",
    },
    "sensex": {
        "name_ja": "S&P BSE SENSEX", "name_en": "BSE SENSEX", "symbol": "^BSESN",
        "wiki_url": "https://en.wikipedia.org/wiki/BSE_SENSEX",
        "ticker_col_candidates": ["BSE code", "Code", "Symbol", "Ticker"],
        "name_col_candidates": ["Companies", "Company", "Name"],
        "sector_col_candidates": ["Sector", "Industry"],
        "market": "IN", "ticker_suffix": ".BO", "digits_only": True, "digits_length": 6,
        "country": "India", "region": "Asia-Pacific", "flag": "🇮🇳",
        "desc": "ボンベイ証券取引所(BSE)に上場するインド主要30銘柄で構成される歴史ある指数。",
    },
    # ========== アメリカ大陸その他 ==========
    "tsx60": {
        "name_ja": "S&P/TSX 60", "name_en": "S&P/TSX 60", "symbol": "^SPTSX",
        "wiki_url": "https://en.wikipedia.org/wiki/S%26P/TSX_60",
        "ticker_col_candidates": ["Ticker", "Symbol", "Code"],
        "name_col_candidates": ["Company", "Name"],
        "sector_col_candidates": ["Sector", "Industry"],
        "market": "CA", "ticker_suffix": ".TO", "digits_only": False,
        "country": "Canada", "region": "Americas", "flag": "🇨🇦",
        "desc": "トロント証券取引所に上場するカナダ大型60銘柄で構成される指数。",
    },
    "ibovespa": {
        "name_ja": "IBOVESPA", "name_en": "IBOVESPA", "symbol": "^BVSP",
        "wiki_url": "https://en.wikipedia.org/wiki/%C3%8Dndice_Bovespa",
        "ticker_col_candidates": ["Ticker", "Symbol", "Code"],
        "name_col_candidates": ["Company", "Name"],
        "sector_col_candidates": ["Sector", "Industry"],
        "market": "BR", "ticker_suffix": ".SA", "digits_only": False,
        "country": "Brazil", "region": "Americas", "flag": "🇧🇷",
        "desc": "ブラジル・サンパウロ証券取引所(B3)上場のブラジル主要銘柄で構成される指数。",
    },
}


# ======================================================================
# Step 1: Wikipedia から構成銘柄リスト取得
# ======================================================================
def normalize_ticker(raw: str, cfg: dict) -> str | None:
    """市場別のticker正規化。数字ベース市場(JP/HK/KR/IN BSE)はzero-pad、文字ベースは大文字化+suffix付与。"""
    raw = str(raw).strip()
    if not raw or raw.lower() == "nan":
        return None
    if cfg.get("digits_only"):
        digits = "".join(ch for ch in raw if ch.isdigit())
        if not digits:
            return None
        dl = cfg.get("digits_length", 4)
        ticker = digits[:dl].zfill(dl) + cfg["ticker_suffix"]
    else:
        base = raw.replace(".", "-").upper()
        # Some indices list tickers with suffix already (e.g. "AIR.PA")
        # Strip known suffix to avoid double-append
        suffix = cfg.get("ticker_suffix", "")
        if suffix and base.endswith(suffix.replace(".", "-").upper()):
            base = base[: -len(suffix)]
        ticker = base + suffix
    return ticker


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Multi-index columns -> flat strings."""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [
            " ".join(str(c) for c in col if str(c) != "nan").strip()
            for col in df.columns
        ]
    else:
        df = df.copy()
        df.columns = [str(c) for c in df.columns]
    return df


def _match_col(columns: list[str], candidates: list[str]) -> str | None:
    for cand in candidates:
        for col in columns:
            if cand in col:
                return col
    return None


def fetch_members_from_wiki(cfg: dict) -> list[dict]:
    # Wikipedia blocks default pandas UA -> fetch via requests with a browser UA
    resp = requests.get(cfg["wiki_url"], headers=WIKI_HEADERS, timeout=30)
    resp.raise_for_status()
    from io import StringIO
    tables = [_flatten_columns(t) for t in pd.read_html(StringIO(resp.text), flavor="lxml")]

    best = None
    best_cols = {}
    best_score = -1
    for t in tables:
        cols = list(t.columns)
        tcol = _match_col(cols, cfg["ticker_col_candidates"])
        ncol = _match_col(cols, cfg["name_col_candidates"])
        scol = _match_col(cols, cfg["sector_col_candidates"])
        score = (10 if tcol else 0) + (5 if ncol else 0) + (2 if scol else 0)
        min_rows = 10 if cfg["name_en"] != "Dow Jones Industrial Average" else 25
        if tcol and ncol and score > best_score and len(t) >= min_rows:
            best_score = score
            best = t
            best_cols = {"ticker": tcol, "name": ncol, "sector": scol}

    if best is None:
        raise RuntimeError(f"No suitable table found for {cfg['name_en']}")

    def pick(row, col_name):
        if col_name and col_name in row.index and pd.notna(row[col_name]):
            return str(row[col_name]).strip()
        return ""

    members = []
    for _, row in best.iterrows():
        raw_ticker = pick(row, best_cols["ticker"])
        name = pick(row, best_cols["name"])
        sector = pick(row, best_cols["sector"])
        if not raw_ticker or not name:
            continue

        # Normalize ticker per market
        ticker = normalize_ticker(raw_ticker, cfg)
        if not ticker:
            continue

        members.append({
            "ticker": ticker,
            "wiki_ticker": raw_ticker,
            "name": name,
            "sector": sector,
        })

    # Deduplicate (Wikipedia sometimes has dupes)
    seen = set()
    uniq = []
    for m in members:
        if m["ticker"] not in seen:
            seen.add(m["ticker"])
            uniq.append(m)
    return uniq


# ======================================================================
# Step 2: yfinance で価格データ一括取得
# ======================================================================
def fetch_prices(tickers: list[str]) -> dict:
    """yf.Tickers で一括取得。info は個別に取るので API コール多め。"""
    result = {}
    if not tickers:
        return result

    print(f"  prices: downloading {len(tickers)} tickers via yf.download()...")
    hist = yf.download(
        tickers, period="5d", interval="1d",
        group_by="ticker", auto_adjust=False, progress=False, threads=True,
    )

    for t in tickers:
        try:
            if len(tickers) == 1:
                df = hist
            else:
                df = hist[t]
            df = df.dropna(how="all")
            if len(df) < 1:
                continue
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) >= 2 else latest
            close = float(latest["Close"])
            prev_close = float(prev["Close"])
            change_pct = (close - prev_close) / prev_close * 100 if prev_close else 0.0
            result[t] = {
                "close": round(close, 2),
                "prev_close": round(prev_close, 2),
                "change_pct": round(change_pct, 2),
                "volume": int(latest.get("Volume", 0) or 0),
                "last_date": str(df.index[-1].date()),
            }
        except Exception as e:
            print(f"    skip {t}: {type(e).__name__}")
    return result


def fetch_info_batch(tickers: list[str], max_items: int | None = None) -> dict:
    """fast_info を並列で取得。Yahoo Finance のレート対策で最大10並列。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    result = {}
    sub = tickers if max_items is None else tickers[:max_items]

    def get_one(t: str):
        try:
            fi = yf.Ticker(t).fast_info
            return t, {
                "market_cap": int(fi.get("market_cap", 0) or 0),
                "currency": fi.get("currency", ""),
            }
        except Exception:
            return t, None

    done = 0
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(get_one, t) for t in sub]
        for f in as_completed(futures):
            t, info = f.result()
            if info:
                result[t] = info
            done += 1
            if done % 100 == 0:
                print(f"    info: {done}/{len(sub)}")
    return result


# ======================================================================
# Step 3: Save JSON
# ======================================================================
def save_json(data: dict, filename: str) -> None:
    path = DATA / filename
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ======================================================================
# Step 4: HTML generation
# ======================================================================
def fmt_num(n: float | int) -> str:
    if n is None or n == 0:
        return "—"
    if abs(n) >= 1_000_000_000_000:
        return f"{n/1_000_000_000_000:.2f}T"
    if abs(n) >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B"
    if abs(n) >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    return f"{n:,.0f}"


def color_class(change_pct: float) -> str:
    if change_pct > 0:
        return "up"
    if change_pct < 0:
        return "down"
    return "flat"


HEAD_TMPL = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta name="robots" content="index,follow">
<link rel="canonical" href="{canonical}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="{ogtype}">
<meta property="og:url" content="{canonical}">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700;900&family=Noto+Sans+JP:wght@400;500;700;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{css_path}">
</head>
<body>
<header class="site-header">
  <div class="container">
    <a class="brand" href="{root_path}">INDEX STOCKS <span class="brand-mark">COMPASS</span></a>
    <nav class="site-nav">
      <a href="{root_path}n225/">日経225</a>
      <a href="{root_path}sp500/">S&amp;P500</a>
      <a href="{root_path}dax40/">DAX</a>
      <a href="{root_path}hsi/">ハンセン</a>
      <a href="{root_path}#all-indices">全20指数 →</a>
    </nav>
  </div>
</header>
"""

PROMO_HTML = """
<section class="promo-musclelove">
  <div class="container">
    <div class="promo-card">
      <div class="promo-icon">💪</div>
      <div class="promo-body">
        <div class="promo-eyebrow">PR · 運営メディア</div>
        <h3>MuscleLove — 筋トレ・フィットネス情報ネットワーク</h3>
        <p>格闘女子・フィジーク・アームレスリング・筋トレ飯など、40+サイトを展開するMuscleLoveを運営中。XとPatreonで限定コンテンツも配信しています。</p>
      </div>
      <div class="promo-cta">
        <a class="btn-promo" href="https://x.com/MuscleGirlLove7" target="_blank" rel="noopener">X @MuscleGirlLove7</a>
        <a class="btn-promo outline" href="https://www.patreon.com/MuscleLove" target="_blank" rel="noopener">Patreon</a>
      </div>
    </div>
  </div>
</section>
"""

FOOT_TMPL = PROMO_HTML + """<footer class="site-footer">
  <div class="container">
    <div><strong>Index Stocks Compass</strong> — 主要株価指数の構成銘柄・株価を毎日自動更新</div>
    <div>最終更新: {updated}</div>
    <div class="small">データ出典: Yahoo Finance / Wikipedia。投資判断は自己責任でお願いします。本サイトは情報提供目的であり、投資勧誘を意図するものではありません。</div>
  </div>
</footer>
</body>
</html>
"""


REGIONS_ORDER = ["Japan", "Americas", "Europe", "Asia-Pacific"]
REGIONS_LABEL = {
    "Japan": "🇯🇵 日本",
    "Americas": "🌎 アメリカ大陸",
    "Europe": "🇪🇺 ヨーロッパ",
    "Asia-Pacific": "🌏 アジア・オセアニア",
}


def _index_card(slug: str, cfg: dict, members: list[dict]) -> str:
    count = len(members)
    pcts = [m["change_pct"] for m in members if m.get("change_pct") is not None]
    avg = sum(pcts) / len(pcts) if pcts else 0.0
    ups = sum(1 for p in pcts if p > 0)
    downs = sum(1 for p in pcts if p < 0)
    cls = color_class(avg)
    return f"""
      <a class="index-card" href="{slug}/">
        <div class="index-head">
          <div>
            <h3>{cfg["flag"]} {cfg["name_ja"]}</h3>
            <div class="index-sub">{cfg["name_en"]} · {count}銘柄</div>
          </div>
          <span class="flag flag-{cfg["market"].lower()}">{cfg["market"]}</span>
        </div>
        <div class="index-metric {cls}">
          <span class="metric-num">{avg:+.2f}%</span>
          <span class="metric-label">構成銘柄平均騰落率</span>
        </div>
        <div class="index-breakdown">
          <span class="up">▲ {ups}</span>
          <span class="down">▼ {downs}</span>
          <span class="flat">— {count - ups - downs}</span>
        </div>
      </a>"""


def render_top(index_data: dict, updated: str) -> str:
    # Group by region
    region_blocks = []
    total_count = sum(len(index_data[s]["members"]) for s in INDICES)
    for region in REGIONS_ORDER:
        slugs_in = [s for s, c in INDICES.items() if c.get("region") == region]
        if not slugs_in:
            continue
        cards = [_index_card(s, INDICES[s], index_data[s]["members"]) for s in slugs_in]
        n_indices = len(slugs_in)
        n_stocks = sum(len(index_data[s]["members"]) for s in slugs_in)
        region_blocks.append(f"""
    <div class="region-block">
      <div class="region-head">
        <h3 class="region-title">{REGIONS_LABEL[region]}</h3>
        <div class="region-sub">{n_indices}指数 · {n_stocks}銘柄</div>
      </div>
      <div class="index-grid">
        {"".join(cards)}
      </div>
    </div>""")

    body = f"""
<section class="hero">
  <div class="container">
    <h1>世界の株価指数を、<br>まるごと毎日アップデート。</h1>
    <p class="lead">日米欧アジア <strong>20指数 / {total_count}銘柄</strong> の構成と株価を毎朝自動で更新。<br>半年ごとの指数入替にも自動追従する、世界の市場の羅針盤。</p>
    <div class="hero-stats">
      <div class="stat"><div class="num">20</div><div class="label">Indices</div></div>
      <div class="stat"><div class="num">{total_count}</div><div class="label">Stocks tracked</div></div>
      <div class="stat"><div class="num">15</div><div class="label">Countries</div></div>
    </div>
  </div>
</section>

<section class="block" id="all-indices">
  <div class="container">
    <div class="section-head">
      <h2>全指数スナップショット</h2>
      <p>地域別に20指数を一覧表示。各カードは構成銘柄数と平均騰落率、上昇/下落銘柄の内訳を示しています。</p>
    </div>
    {"".join(region_blocks)}
  </div>
</section>

<section class="block alt">
  <div class="container">
    <div class="section-head">
      <h2>このサイトについて</h2>
      <p>Index Stocks Compass は、世界の主要株価指数に採用されている全銘柄の最新株価・前日比を毎日自動集計・公開する情報サイトです。構成銘柄の変更（定期入替・臨時入替）も自動追従します。プロの投資家から初学者まで、「今、この指数に何が入っているか」を把握するための羅針盤としてお使いください。</p>
    </div>
  </div>
</section>
"""
    head = HEAD_TMPL.format(
        lang="ja",
        title=f"Index Stocks Compass | 世界20指数{total_count}銘柄の構成銘柄と株価を毎日自動更新",
        desc=f"日経225・S&P500・DAX・FTSE・ハンセン・NIFTY等、世界20指数{total_count}銘柄の構成と株価を毎日自動集計。構成銘柄変更も自動追従。",
        canonical=BASE_URL + "/",
        ogtype="website",
        css_path="assets/style.css",
        root_path="",
    )
    return head + body + FOOT_TMPL.format(updated=updated)


def render_index(slug: str, cfg: dict, members: list[dict], updated: str) -> str:
    rows = []
    # Sort by market_cap desc if available, else name
    def key(m):
        return -(m.get("market_cap") or 0)
    members_sorted = sorted(members, key=key)
    for m in members_sorted:
        chg = m.get("change_pct")
        cls = color_class(chg) if chg is not None else "flat"
        chg_str = f"{chg:+.2f}%" if chg is not None else "—"
        close = m.get("close")
        close_str = f"{close:,.2f}" if close is not None else "—"
        mcap = fmt_num(m.get("market_cap") or 0)
        sector = m.get("sector", "") or ""
        # yfinance uses "-" in tickers but Yahoo Finance URL uses "."
        yahoo_tkr = m["ticker"].replace("-", ".")
        yurl = f"https://finance.yahoo.com/quote/{yahoo_tkr}"
        rows.append(f"""
        <tr class="{cls}">
          <td class="t-ticker"><a href="{yurl}" target="_blank" rel="noopener">{m['ticker']}</a></td>
          <td class="t-name">{m['name']}</td>
          <td class="t-sector">{sector}</td>
          <td class="t-num">{close_str}</td>
          <td class="t-num {cls}">{chg_str}</td>
          <td class="t-num">{mcap}</td>
        </tr>""")

    body = f"""
<section class="page-hero">
  <div class="container">
    <div class="breadcrumb"><a href="../">ホーム</a> › {cfg["name_ja"]}</div>
    <h1>{cfg["flag"]} {cfg["name_ja"]}</h1>
    <p class="lead">{cfg["desc"]}</p>
    <div class="hero-stats">
      <div class="stat"><div class="num">{len(members)}</div><div class="label">構成銘柄</div></div>
      <div class="stat"><div class="num">{cfg["country"]}</div><div class="label">上場国</div></div>
      <div class="stat"><div class="num">{cfg["symbol"]}</div><div class="label">指数シンボル</div></div>
    </div>
  </div>
</section>

<section class="block">
  <div class="container">
    <div class="table-wrap">
      <table class="stock-table">
        <thead>
          <tr><th>ティッカー</th><th>企業名</th><th>セクター</th><th class="t-num">終値</th><th class="t-num">前日比</th><th class="t-num">時価総額</th></tr>
        </thead>
        <tbody>
          {"".join(rows)}
        </tbody>
      </table>
    </div>
  </div>
</section>
"""
    head = HEAD_TMPL.format(
        lang="ja",
        title=f"{cfg['name_ja']} 構成銘柄一覧 | Index Stocks Compass",
        desc=f"{cfg['name_ja']}（{cfg['name_en']}）の全構成銘柄{len(members)}社の最新株価・前日比・時価総額・セクターを毎日自動更新。",
        canonical=f"{BASE_URL}/{slug}/",
        ogtype="article",
        css_path="../assets/style.css",
        root_path="../",
    )
    return head + body + FOOT_TMPL.format(updated=updated)


def render_sitemap(updated_date: str) -> str:
    urls = [f"{BASE_URL}/"]
    urls += [f"{BASE_URL}/{slug}/" for slug in INDICES]
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        lines.append(
            f"  <url><loc>{u}</loc><lastmod>{updated_date}</lastmod>"
            f"<changefreq>daily</changefreq><priority>0.9</priority></url>"
        )
    lines.append("</urlset>")
    return "\n".join(lines)


# ======================================================================
# Main
# ======================================================================
def main():
    updated_human = NOW.strftime("%Y-%m-%d %H:%M JST")
    print(f"=== Index Stocks Compass update @ {updated_human} ===\n")

    index_data = {}

    for slug, cfg in INDICES.items():
        print(f"[{slug}] {cfg['name_en']}")
        try:
            members = fetch_members_from_wiki(cfg)
            print(f"  members: {len(members)} from wiki")
        except Exception as e:
            print(f"  ❌ wiki scrape failed: {e}")
            members = []

        tickers = [m["ticker"] for m in members]
        prices = fetch_prices(tickers) if tickers else {}
        print(f"  prices resolved: {len(prices)}/{len(tickers)}")

        # top-N market caps via fast_info (limit to keep runtime low on CI)
        info = fetch_info_batch(tickers, max_items=len(tickers))
        print(f"  info resolved: {len(info)}/{len(tickers)}")

        for m in members:
            p = prices.get(m["ticker"], {})
            i = info.get(m["ticker"], {})
            m["close"] = p.get("close")
            m["prev_close"] = p.get("prev_close")
            m["change_pct"] = p.get("change_pct")
            m["volume"] = p.get("volume")
            m["last_date"] = p.get("last_date")
            m["market_cap"] = i.get("market_cap", 0)
            m["currency"] = i.get("currency", "")

        save_json({"updated": updated_human, "members": members}, f"{slug}.json")
        index_data[slug] = {"members": members}
        print()

    # Render HTML
    print("=== Render HTML ===")
    (ROOT / "index.html").write_text(render_top(index_data, updated_human), encoding="utf-8")
    print("  ✓ index.html")
    for slug, cfg in INDICES.items():
        slug_dir = ROOT / slug
        slug_dir.mkdir(exist_ok=True)
        (slug_dir / "index.html").write_text(
            render_index(slug, cfg, index_data[slug]["members"], updated_human), encoding="utf-8"
        )
        print(f"  ✓ {slug}/index.html")

    (ROOT / "sitemap.xml").write_text(render_sitemap(TODAY), encoding="utf-8")
    print("  ✓ sitemap.xml")

    # robots.txt (static but ensure present)
    (ROOT / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {BASE_URL}/sitemap.xml\n", encoding="utf-8"
    )
    print("  ✓ robots.txt")

    print(f"\n=== Done @ {datetime.now(JST).strftime('%H:%M:%S JST')} ===")


if __name__ == "__main__":
    main()
