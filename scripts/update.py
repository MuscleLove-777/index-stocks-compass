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
    "n225": {
        "name_ja": "日経平均株価 (Nikkei 225)",
        "name_en": "Nikkei 225",
        "symbol": "^N225",
        "wiki_url": "https://topforeignstocks.com/indices/the-components-of-the-nikkei-225-index/",
        "wiki_table_match": None,
        "ticker_col_candidates": ["Code", "Symbol", "Ticker", "コード"],
        "name_col_candidates": ["Company Name", "Company", "Name", "銘柄名"],
        "sector_col_candidates": ["Sector", "Industry", "業種"],
        "market": "JP",
        "ticker_suffix": ".T",
        "country": "Japan",
        "desc": "日本の代表的な225銘柄で構成される株価平均型指数。東証プライム市場から選定。",
    },
    "topix-core30": {
        "name_ja": "TOPIX Core30",
        "name_en": "TOPIX Core30",
        "symbol": "^TPX",
        "wiki_url": "https://ja.wikipedia.org/wiki/TOPIX_Core_30",
        "wiki_table_match": None,
        "ticker_col_candidates": ["銘柄コード", "コード", "証券コード", "Code"],
        "name_col_candidates": ["銘柄名", "企業名", "社名", "名称", "Company"],
        "sector_col_candidates": ["業種", "セクター", "Sector"],
        "market": "JP",
        "ticker_suffix": ".T",
        "country": "Japan",
        "desc": "TOPIX構成銘柄のうち時価総額・流動性最上位の30銘柄で構成される指数。",
    },
    "sp500": {
        "name_ja": "S&P 500",
        "name_en": "S&P 500",
        "symbol": "^GSPC",
        "wiki_url": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "wiki_table_match": "Symbol",
        "ticker_col_candidates": ["Symbol", "Ticker symbol"],
        "name_col_candidates": ["Security", "Company"],
        "sector_col_candidates": ["GICS Sector", "Sector"],
        "market": "US",
        "ticker_suffix": "",
        "country": "United States",
        "desc": "米国を代表する大型株500銘柄で構成される時価総額加重平均指数。",
    },
    "nasdaq100": {
        "name_ja": "NASDAQ-100",
        "name_en": "NASDAQ-100",
        "symbol": "^NDX",
        "wiki_url": "https://en.wikipedia.org/wiki/Nasdaq-100",
        "wiki_table_match": "Ticker",
        "ticker_col_candidates": ["Ticker", "Symbol"],
        "name_col_candidates": ["Company", "Security"],
        "sector_col_candidates": ["GICS Sector", "Sector"],
        "market": "US",
        "ticker_suffix": "",
        "country": "United States",
        "desc": "NASDAQ上場の金融を除く時価総額上位100銘柄で構成される指数。",
    },
    "dow30": {
        "name_ja": "NYダウ (Dow Jones Industrial Average)",
        "name_en": "Dow Jones Industrial Average",
        "symbol": "^DJI",
        "wiki_url": "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average",
        "wiki_table_match": "Symbol",
        "ticker_col_candidates": ["Symbol", "Ticker"],
        "name_col_candidates": ["Company", "Security"],
        "sector_col_candidates": ["Industry", "GICS Sector", "Sector"],
        "market": "US",
        "ticker_suffix": "",
        "country": "United States",
        "desc": "米国を代表する30の優良企業で構成される価格加重平均指数。",
    },
}


# ======================================================================
# Step 1: Wikipedia から構成銘柄リスト取得
# ======================================================================
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

        # Japanese code -> "7203" (4-digit) -> "7203.T"
        if cfg["market"] == "JP":
            digits = "".join(ch for ch in raw_ticker if ch.isdigit())
            if len(digits) < 4:
                continue
            ticker = digits[:4] + cfg["ticker_suffix"]
        else:
            ticker = raw_ticker.replace(".", "-").upper()  # BRK.B -> BRK-B for yfinance

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
    """fast_info で時価総額など軽く取る。tickerすべて試すと時間かかるのでmax_itemsで制御可能。"""
    result = {}
    sub = tickers if max_items is None else tickers[:max_items]
    for i, t in enumerate(sub):
        try:
            fi = yf.Ticker(t).fast_info
            result[t] = {
                "market_cap": int(fi.get("market_cap", 0) or 0),
                "currency": fi.get("currency", ""),
            }
        except Exception:
            pass
        if i % 50 == 49:
            print(f"    info: {i+1}/{len(sub)}")
            time.sleep(0.3)
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
      <a href="{root_path}topix-core30/">TOPIX30</a>
      <a href="{root_path}sp500/">S&amp;P500</a>
      <a href="{root_path}nasdaq100/">NASDAQ100</a>
      <a href="{root_path}dow30/">NYダウ</a>
    </nav>
  </div>
</header>
"""

FOOT_TMPL = """<footer class="site-footer">
  <div class="container">
    <div><strong>Index Stocks Compass</strong> — 主要株価指数の構成銘柄・株価を毎日自動更新</div>
    <div>最終更新: {updated}</div>
    <div class="small">データ出典: Yahoo Finance / Wikipedia。投資判断は自己責任でお願いします。本サイトは情報提供目的であり、投資勧誘を意図するものではありません。</div>
  </div>
</footer>
</body>
</html>
"""


def render_top(index_data: dict, updated: str) -> str:
    cards = []
    for slug, cfg in INDICES.items():
        members = index_data[slug]["members"]
        count = len(members)
        # average change_pct across available prices
        pcts = [m["change_pct"] for m in members if m.get("change_pct") is not None]
        avg = sum(pcts) / len(pcts) if pcts else 0.0
        ups = sum(1 for p in pcts if p > 0)
        downs = sum(1 for p in pcts if p < 0)
        cls = color_class(avg)
        cards.append(f"""
      <a class="index-card" href="{slug}/">
        <div class="index-head">
          <div>
            <h3>{cfg["name_ja"]}</h3>
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
      </a>""")

    body = f"""
<section class="hero">
  <div class="container">
    <h1>株価指数の構成銘柄を、<br>毎日まるごと追跡。</h1>
    <p class="lead">日経225 · TOPIX Core30 · S&amp;P 500 · NASDAQ-100 · NYダウ。<br>5つの主要指数の構成銘柄と株価を毎朝自動で更新し、ワンクリックで俯瞰できます。</p>
  </div>
</section>

<section class="block">
  <div class="container">
    <div class="section-head">
      <h2>主要指数スナップショット</h2>
      <p>各指数の最新の構成銘柄数と、構成銘柄の平均騰落率を一覧表示。</p>
    </div>
    <div class="index-grid">
      {"".join(cards)}
    </div>
  </div>
</section>

<section class="block alt">
  <div class="container">
    <div class="section-head">
      <h2>このサイトについて</h2>
      <p>Index Stocks Compass は、日米の主要株価指数に採用されている全銘柄の最新株価・前日比を毎日自動集計・公開する情報サイトです。構成銘柄の変更（定期入替・臨時入替）も週次で自動追従します。プロの投資家から初学者まで、「今、この指数に何が入っているか」を把握するための羅針盤としてお使いください。</p>
    </div>
  </div>
</section>
"""
    head = HEAD_TMPL.format(
        lang="ja",
        title="Index Stocks Compass | 日経225・TOPIX・S&P500の構成銘柄を毎日自動更新",
        desc="日経平均・TOPIX Core30・S&P500・NASDAQ100・NYダウの構成銘柄と最新株価を毎日自動で集計。構成銘柄変更の追跡も自動化。",
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
    <h1>{cfg["name_ja"]}</h1>
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
