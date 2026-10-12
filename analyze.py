"""
analyze.py — Retail Sector Financial Analysis & DCF Dashboard
=============================================================
Reads from:
  • retail_financials.db  (built by fetch_financials.py)
  • mda_texts/*.txt       (built by fetch_mda_text.py)

Produces:
  • retail_analysis_report.html  — self-contained interactive report
  • dcf_summary.csv              — DCF valuation table

Dependencies:
    pip install pandas plotly

Usage:
    python analyze.py
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

DB_PATH  = Path("retail_financials.db")
MDA_DIR  = Path("mda_texts")
OUT_HTML = Path("retail_analysis_report.html")
OUT_CSV  = Path("dcf_summary.csv")

# DCF assumptions (clearly labelled so reviewers know they are inputs)
WACC       = 0.09    # Weighted-average cost of capital
TAX_RATE   = 0.21    # US statutory corporate rate
TG_RATE    = 0.025   # Long-run terminal growth rate (~nominal GDP)
PROJ_YEARS = 5       # Projection horizon

COMPANY_NAMES: dict[str, str] = {
    "WMT":  "Walmart",
    "TGT":  "Target",
    "COST": "Costco",
    "TJX":  "TJX Companies",
    "DG":   "Dollar General",
    "ROST": "Ross Stores",
    "BBY":  "Best Buy",
    "KSS":  "Kohl's",
    "DLTR": "Dollar Tree",
    "M":    "Macy's",
}

# One distinct color per ticker (Set2 + Pastel)
_PALETTE = (
    px.colors.qualitative.Set2
    + px.colors.qualitative.Pastel
    + px.colors.qualitative.Safe
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. DATA LOADING
# ─────────────────────────────────────────────────────────────────────────────

def load_financials() -> pd.DataFrame:
    """
    Load all rows from SQLite and pivot so each row is one
    (ticker, fiscal_year) observation with metrics as columns.
    """
    conn = sqlite3.connect(DB_PATH)
    raw = pd.read_sql_query(
        "SELECT ticker, metric, fiscal_year, value "
        "FROM financials ORDER BY ticker, fiscal_year, metric",
        conn,
    )
    conn.close()

    wide = raw.pivot_table(
        index=["ticker", "fiscal_year"],
        columns="metric",
        values="value",
        aggfunc="last",   # prefer most-recently-filed value for each cell
    ).reset_index()
    wide.columns.name = None
    wide["company"] = wide["ticker"].map(COMPANY_NAMES)
    return wide.sort_values(["ticker", "fiscal_year"]).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# 2. RATIO ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def compute_ratios(df: pd.DataFrame) -> pd.DataFrame:
    """Derive standard financial KPIs from raw GAAP line items."""
    d = df.copy()
    rev = d["Revenues"].replace(0, np.nan)

    # ── Profitability
    d["GrossMarginPct"]     = d["GrossProfit"]          / rev * 100
    d["OperatingMarginPct"] = d["OperatingIncomeLoss"]  / rev * 100
    d["NetMarginPct"]       = d["NetIncomeLoss"]         / rev * 100

    # ── Liquidity
    d["CurrentRatio"] = d["AssetsCurrent"] / d["LiabilitiesCurrent"].replace(0, np.nan)
    d["CashRatio"]    = (
        d["CashAndCashEquivalentsAtCarryingValue"]
        / d["LiabilitiesCurrent"].replace(0, np.nan)
    )

    # ── Leverage
    eq = d["StockholdersEquity"].replace(0, np.nan)
    d["DebtToEquity"] = d["Liabilities"] / eq

    # ── Returns
    assets = d["Assets"].replace(0, np.nan)
    d["ROAPct"] = d["NetIncomeLoss"] / assets * 100
    d["ROEPct"] = d["NetIncomeLoss"] / eq     * 100

    # ── Growth (requires sort)
    d = d.sort_values(["ticker", "fiscal_year"])
    d["RevenueGrowthPct"] = d.groupby("ticker")["Revenues"].pct_change() * 100

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 3. DCF MODEL
# ─────────────────────────────────────────────────────────────────────────────

def compute_dcf(df: pd.DataFrame) -> pd.DataFrame:
    """
    Simplified 5-year DCF using NOPAT as a free-cash-flow proxy.

        NOPAT  = OperatingIncomeLoss × (1 – tax_rate)
        FCF[t] = NOPAT_base × (1 + g)^t
        PV     = Σ FCF[t]/(1+WACC)^t  +  TV/(1+WACC)^n
        TV     = FCF[n] × (1+TGR) / (WACC – TGR)

    Note: D&A, CapEx, and working-capital changes are excluded because
    they are not available from the XBRL companyfacts endpoint.
    This is an academic approximation; clearly label as such.
    """
    records = []

    for ticker, grp in df.groupby("ticker"):
        grp   = grp.sort_values("fiscal_year")
        valid = grp.dropna(subset=["OperatingIncomeLoss"])
        if len(valid) < 2:
            continue

        nopat = valid["OperatingIncomeLoss"] * (1 - TAX_RATE)
        base  = float(nopat.iloc[-1])
        n_obs = len(nopat)

        # Historical CAGR of NOPAT
        if nopat.iloc[0] > 0 and nopat.iloc[-1] > 0 and n_obs > 1:
            hist_g = float((nopat.iloc[-1] / nopat.iloc[0]) ** (1 / (n_obs - 1)) - 1)
        else:
            hist_g = 0.03

        g = float(np.clip(hist_g, -0.05, 0.20))   # cap extreme outliers

        # Present value of projected FCFs
        pv_fcfs = sum(
            base * (1 + g) ** yr / (1 + WACC) ** yr
            for yr in range(1, PROJ_YEARS + 1)
        )

        # Terminal value (Gordon Growth Model)
        terminal_fcf = base * (1 + g) ** PROJ_YEARS * (1 + TG_RATE)
        tv_pv        = (terminal_fcf / (WACC - TG_RATE)) / (1 + WACC) ** PROJ_YEARS

        ev = pv_fcfs + tv_pv

        records.append({
            "Ticker":               ticker,
            "Company":              COMPANY_NAMES.get(ticker, ticker),
            "NOPAT Base ($B)":      round(base / 1e9, 2),
            "Hist. Growth (%)":     round(hist_g * 100, 1),
            "Applied Growth (%)":   round(g * 100, 1),
            "PV of FCFs ($B)":      round(pv_fcfs / 1e9, 2),
            "Terminal Value ($B)":  round(tv_pv / 1e9, 2),
            "Enterprise Value ($B)": round(ev / 1e9, 2),
        })

    return (
        pd.DataFrame(records)
        .sort_values("Enterprise Value ($B)", ascending=False)
        .reset_index(drop=True)
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. MD&A SENTIMENT SCORING (lexicon-based, no external models needed)
# ─────────────────────────────────────────────────────────────────────────────

_BULLISH = frozenset({
    "growth", "grew", "increase", "increased", "higher", "strong", "record",
    "improved", "improvement", "expansion", "gain", "gains", "exceeded",
    "outperform", "momentum", "robust", "solid", "favorable", "benefit",
    "benefits", "opportunity", "opportunities", "profitable", "profitability",
    "accelerate", "accelerating", "efficient", "efficiency", "outpaced",
    "recovery", "demand", "invested", "achieve", "achieved", "confidence",
    "disciplined", "innovative", "strength", "strengths", "positive",
})

_CAUTIONARY = frozenset({
    "decrease", "decreased", "decline", "declined", "loss", "losses", "risk",
    "risks", "challenge", "challenges", "adverse", "headwind", "headwinds",
    "difficult", "difficulty", "pressure", "pressures", "fell", "lower",
    "weakness", "weaknesses", "uncertainty", "inflation", "disruption",
    "disruptions", "deterioration", "impairment", "restructuring", "slowdown",
    "shrinkage", "unfavorable", "volatile", "volatility", "competition",
    "competitive", "increased costs", "tariffs", "debt", "layoffs", "elevated",
})

MIN_MDA_CHARS = 5_000   # skip stub files

# Tickers whose MD&A text couldn't be reliably extracted.
# Their financial DB data is still used for ratios and DCF.
MDA_EXCLUDE = {"DLTR"}


def score_mda(text: str) -> dict:
    """Return sentiment metrics for one MD&A document."""
    words = re.findall(r"[a-z]+", text.lower())
    total = len(words)
    if total == 0:
        return {"sentiment": 0.0, "bullish_ct": 0, "cautionary_ct": 0}

    bullish    = sum(1 for w in words if w in _BULLISH)
    cautionary = sum(1 for w in words if w in _CAUTIONARY)
    # Scale to per-1,000-words so short and long docs are comparable
    net_score  = (bullish - cautionary) / total * 1000

    return {
        "sentiment":     round(net_score, 3),
        "bullish_ct":    bullish,
        "cautionary_ct": cautionary,
        "word_count":    total,
    }


def load_mda_sentiments() -> pd.DataFrame:
    """Score every valid MD&A file and return a tidy DataFrame."""
    records = []
    for fpath in sorted(MDA_DIR.glob("*.txt")):
        parts = fpath.stem.split("_")
        if len(parts) < 2:
            continue
        ticker = parts[0]
        if ticker in MDA_EXCLUDE:
            continue   # skip companies with unreliable extractions
        try:
            year = int(parts[1])
        except ValueError:
            continue

        text = fpath.read_text(encoding="utf-8", errors="ignore")
        if len(text) < MIN_MDA_CHARS:
            continue   # skip stubs

        scored = score_mda(text)
        records.append({
            "ticker":       ticker,
            "company":      COMPANY_NAMES.get(ticker, ticker),
            "year":         year,
            "char_count":   len(text),
            **scored,
        })

    return pd.DataFrame(records).sort_values(["ticker", "year"]).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# 5. CHARTS
# ─────────────────────────────────────────────────────────────────────────────

def _color_map(tickers: list[str]) -> dict[str, str]:
    return {t: _PALETTE[i % len(_PALETTE)] for i, t in enumerate(sorted(tickers))}


def fig_revenue_trends(df: pd.DataFrame) -> go.Figure:
    cmap = _color_map(df["ticker"].unique())
    fig  = go.Figure()
    for ticker, grp in df.groupby("ticker"):
        grp = grp.dropna(subset=["Revenues"])
        fig.add_trace(go.Scatter(
            x=grp["fiscal_year"], y=(grp["Revenues"] / 1e9).round(2),
            name=COMPANY_NAMES.get(ticker, ticker),
            mode="lines+markers",
            line=dict(color=cmap[ticker], width=2.5),
            marker=dict(size=7),
            hovertemplate="%{x}: $%{y:.1f}B<extra></extra>",
        ))
    fig.update_layout(
        title="Annual Revenue — 5-Year Trend ($B)",
        xaxis_title="Fiscal Year", yaxis_title="Revenue ($B)",
        legend_title="Company", hovermode="x unified",
    )
    return fig


def fig_revenue_cagr(df: pd.DataFrame) -> go.Figure:
    records = []
    for ticker, grp in df.groupby("ticker"):
        g   = grp.dropna(subset=["Revenues"]).sort_values("fiscal_year")
        n   = int(g["fiscal_year"].iloc[-1]) - int(g["fiscal_year"].iloc[0])
        r0, rn = g["Revenues"].iloc[0], g["Revenues"].iloc[-1]
        cagr = ((rn / r0) ** (1 / n) - 1) * 100 if (r0 > 0 and n > 0) else 0.0
        records.append({"ticker": ticker, "cagr": round(cagr, 2)})

    cdf = pd.DataFrame(records).sort_values("cagr", ascending=False)
    colors = ["#27ae60" if v >= 0 else "#e74c3c" for v in cdf["cagr"]]

    fig = go.Figure(go.Bar(
        x=cdf["ticker"], y=cdf["cagr"],
        marker_color=colors,
        text=[f"{v:+.1f}%" for v in cdf["cagr"]],
        textposition="outside",
    ))
    fig.add_hline(y=0, line_color="black", line_width=0.8)
    fig.update_layout(
        title="Revenue CAGR — Full 5-Year Window (%)",
        xaxis_title="Company", yaxis_title="CAGR (%)",
        yaxis=dict(zeroline=True),
    )
    return fig


def fig_margin_bars(df: pd.DataFrame) -> go.Figure:
    latest = (
        df.dropna(subset=["GrossMarginPct"])
        .sort_values("fiscal_year")
        .groupby("ticker").last()
        .reset_index()
        .sort_values("GrossMarginPct", ascending=False)
    )

    fig = make_subplots(
        rows=1, cols=3,
        subplot_titles=("Gross Margin (%)", "Operating Margin (%)", "Net Margin (%)"),
        shared_yaxes=False,
    )
    cmap = _color_map(latest["ticker"].tolist())

    for col_idx, metric in enumerate(
        ["GrossMarginPct", "OperatingMarginPct", "NetMarginPct"], 1
    ):
        vals   = latest[metric].round(1)
        colors = [cmap[t] for t in latest["ticker"]]
        fig.add_trace(
            go.Bar(
                x=latest["ticker"], y=vals,
                marker_color=colors,
                text=[f"{v:.1f}%" for v in vals],
                textposition="outside",
                showlegend=False,
            ),
            row=1, col=col_idx,
        )

    fig.update_layout(
        title="Profitability Margins — Most Recent Fiscal Year",
        height=460,
        margin=dict(t=80),
    )
    return fig


def fig_health_heatmap(df: pd.DataFrame) -> go.Figure:
    METRICS = {
        "GrossMarginPct":     "Gross Margin (%)",
        "OperatingMarginPct": "Operating Margin (%)",
        "NetMarginPct":       "Net Margin (%)",
        "CurrentRatio":       "Current Ratio",
        "DebtToEquity":       "Debt / Equity",
        "ROAPct":             "ROA (%)",
        "ROEPct":             "ROE (%)",
    }

    latest = (
        df.sort_values("fiscal_year")
        .groupby("ticker").last()
        .reset_index()
        .sort_values("ticker")
    )

    tickers = latest["ticker"].tolist()
    z_vals, text_vals = [], []
    for metric, label in METRICS.items():
        row_z, row_t = [], []
        for _, r in latest.iterrows():
            v = r.get(metric, np.nan)
            row_z.append(float(v) if pd.notna(v) else 0.0)
            row_t.append(f"{v:.2f}" if pd.notna(v) else "N/A")
        z_vals.append(row_z)
        text_vals.append(row_t)

    fig = go.Figure(go.Heatmap(
        z=z_vals, x=tickers, y=list(METRICS.values()),
        text=text_vals,
        texttemplate="%{text}",
        colorscale="RdYlGn",
        hoverongaps=False,
    ))
    fig.update_layout(
        title="Financial Health Heatmap — Most Recent Fiscal Year",
        height=380,
    )
    return fig


def fig_dcf_chart(dcf: pd.DataFrame) -> go.Figure:
    d   = dcf.sort_values("Enterprise Value ($B)")
    cmap = _color_map(d["Ticker"].tolist())

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=d["PV of FCFs ($B)"],
        y=d["Ticker"],
        orientation="h",
        name="PV of FCFs",
        marker_color=[cmap[t] for t in d["Ticker"]],
        hovertemplate="%{y}: PV FCFs $%{x:.1f}B<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=d["Terminal Value ($B)"],
        y=d["Ticker"],
        orientation="h",
        name="Terminal Value",
        marker_color=[cmap[t] for t in d["Ticker"]],
        opacity=0.5,
        hovertemplate="%{y}: TV $%{x:.1f}B<extra></extra>",
    ))
    fig.update_layout(
        barmode="stack",
        title=(
            f"DCF Enterprise Value Estimate (Stacked: FCFs + Terminal Value)<br>"
            f"<sup>WACC={WACC*100:.0f}%  |  TGR={TG_RATE*100:.1f}%  |  "
            f"{PROJ_YEARS}-year horizon  |  NOPAT used as FCF proxy</sup>"
        ),
        xaxis_title="Value ($B)",
        legend=dict(orientation="h", y=-0.15),
        height=440,
        margin=dict(l=60),
    )
    return fig


def fig_sentiment(sdf: pd.DataFrame) -> go.Figure:
    cmap = _color_map(sdf["ticker"].unique())
    fig  = go.Figure()

    for ticker, grp in sdf.groupby("ticker"):
        grp = grp.sort_values("year")
        fig.add_trace(go.Scatter(
            x=grp["year"], y=grp["sentiment"],
            name=COMPANY_NAMES.get(ticker, ticker),
            mode="lines+markers",
            line=dict(color=cmap[ticker], width=2.5),
            marker=dict(size=8),
            hovertemplate=f"{ticker} %{{x}}: %{{y:.2f}}<extra></extra>",
        ))

    fig.add_hline(y=0, line_dash="dot", line_color="grey",
                  annotation_text="Neutral", annotation_position="bottom right")
    fig.update_layout(
        title=(
            "10-K MD&A Tone Index by Year<br>"
            "<sup>Positive = bullish language dominates | "
            "Negative = cautionary language dominates (net score per 1,000 words)</sup>"
        ),
        xaxis_title="Filing Year",
        yaxis_title="Net Sentiment Score",
        legend_title="Company",
        hovermode="x unified",
    )
    return fig


def fig_sentiment_heatmap(sdf: pd.DataFrame) -> go.Figure:
    pivot = sdf.pivot(index="ticker", columns="year", values="sentiment")
    pivot = pivot.sort_index()

    fig = go.Figure(go.Heatmap(
        z=pivot.values.tolist(),
        x=[str(c) for c in pivot.columns],
        y=pivot.index.tolist(),
        text=[[f"{v:.2f}" if pd.notna(v) else "N/A" for v in row]
              for row in pivot.values.tolist()],
        texttemplate="%{text}",
        colorscale="RdYlGn",
        zmid=0,
    ))
    fig.update_layout(
        title="MD&A Sentiment Heatmap (per company × year)",
        xaxis_title="Filing Year",
        yaxis_title="Company",
        height=380,
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# 6. HTML REPORT ASSEMBLY
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
<style>
  *, *::before, *::after { box-sizing: border-box; }
  body   { font-family: 'Helvetica Neue', Arial, sans-serif;
           background: #f0f4f8; margin: 0; color: #1a252f; }
  header { background: linear-gradient(135deg, #1a252f 0%, #2c3e50 100%);
           color: #ecf0f1; padding: 36px 48px; }
  header h1 { margin: 0 0 6px; font-size: 1.75rem; letter-spacing: .4px; }
  header p  { margin: 0; font-size: .88rem; color: #95a5a6; }
  nav   { background: #2c3e50; padding: 10px 48px; position: sticky; top: 0;
          z-index: 999; display: flex; gap: 24px; }
  nav a { color: #ecf0f1; text-decoration: none; font-size: .82rem;
          font-weight: 600; letter-spacing: .3px; }
  nav a:hover { color: #3498db; }
  .section      { padding: 36px 48px; }
  .section:nth-child(odd)  { background: #ffffff; }
  .section:nth-child(even) { background: #f8fafc; }
  .section h2 { font-size: 1.1rem; font-weight: 700; color: #2c3e50;
                border-left: 4px solid #3498db; padding-left: 12px;
                margin-bottom: 20px; }
  table  { width: 100%; border-collapse: collapse; font-size: .83rem; }
  thead th { background: #2c3e50; color: #ecf0f1; padding: 9px 13px;
             text-align: left; font-weight: 600; }
  tbody td { padding: 8px 13px; border-bottom: 1px solid #e2e8f0; }
  tbody tr:hover td { background: #eaf1fb; }
  .disclaimer { background: #fff8e1; border-left: 4px solid #f59e0b;
                padding: 12px 16px; border-radius: 4px;
                font-size: .8rem; margin-top: 14px; line-height: 1.6; }
  footer { text-align: center; padding: 24px; font-size: .75rem;
           color: #7f8c8d; background: #1a252f; }
</style>
"""

def _dcf_table_html(dcf: pd.DataFrame) -> str:
    rows = "".join(
        f"""<tr>
          <td><b>{r['Ticker']}</b></td>
          <td>{r['Company']}</td>
          <td>${r['NOPAT Base ($B)']:.2f}B</td>
          <td>{r['Hist. Growth (%)']:.1f}%</td>
          <td>{r['Applied Growth (%)']:.1f}%</td>
          <td>${r['PV of FCFs ($B)']:.2f}B</td>
          <td>${r['Terminal Value ($B)']:.2f}B</td>
          <td><b>${r['Enterprise Value ($B)']:.2f}B</b></td>
        </tr>"""
        for _, r in dcf.iterrows()
    )
    return f"""
    <table>
      <thead>
        <tr>
          <th>Ticker</th><th>Company</th><th>NOPAT Base</th>
          <th>Hist. Growth</th><th>Applied Growth</th>
          <th>PV of FCFs</th><th>Terminal Value</th>
          <th>Enterprise Value ▼</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    <div class="disclaimer">
      <b>⚠ Academic model — not investment advice.</b><br>
      FCF proxy = NOPAT = Operating Income × (1 − {TAX_RATE:.0%}).
      D&amp;A, CapEx, and working-capital changes excluded (not available
      from XBRL companyfacts endpoint).
      WACC = {WACC:.0%} | Terminal growth = {TG_RATE:.1%} | Horizon = {PROJ_YEARS} years.
    </div>"""


def build_report(df: pd.DataFrame, dcf: pd.DataFrame, sdf: pd.DataFrame) -> None:
    """Assemble all charts and tables into one self-contained HTML file."""

    sections: list[tuple[str, str, str]] = [
        ("revenue",    "Revenue Trends",         fig_revenue_trends(df).to_html(full_html=False, include_plotlyjs=False)),
        ("cagr",       "Revenue CAGR",            fig_revenue_cagr(df).to_html(full_html=False, include_plotlyjs=False)),
        ("margins",    "Profitability Margins",   fig_margin_bars(df).to_html(full_html=False, include_plotlyjs=False)),
        ("health",     "Financial Health",        fig_health_heatmap(df).to_html(full_html=False, include_plotlyjs=False)),
        ("dcf-chart",  "DCF Enterprise Value",    fig_dcf_chart(dcf).to_html(full_html=False, include_plotlyjs=False)),
        ("dcf-table",  "DCF Valuation Table",     _dcf_table_html(dcf)),
    ]

    if not sdf.empty:
        sections += [
            ("sentiment",      "MD&A Sentiment Trends",  fig_sentiment(sdf).to_html(full_html=False, include_plotlyjs=False)),
            ("sent-heatmap",   "MD&A Sentiment Heatmap", fig_sentiment_heatmap(sdf).to_html(full_html=False, include_plotlyjs=False)),
        ]

    nav_links = "".join(
        f'<a href="#{sid}">{label}</a>'
        for sid, label, _ in sections
    )
    section_html = "".join(
        f'<div class="section" id="{sid}"><h2>{label}</h2>{body}</div>'
        for sid, label, body in sections
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Retail Sector — Financial Analysis & DCF</title>
  <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
  {_CSS}
</head>
<body>
  <header>
    <h1>🛒 US Retail Sector — Financial Analysis & DCF Dashboard</h1>
    <p>10 companies  ·  SEC EDGAR XBRL data (FY 2022–2026)  ·  10-K MD&amp;A sentiment analysis  ·  Built with Python</p>
  </header>
  <nav>{nav_links}</nav>
  {section_html}
  <footer>
    Data: SEC EDGAR XBRL API (companyfacts) &amp; 10-K Item 7 text  ·
    Sentiment: finance-domain lexicon  ·
    All figures USD  ·  Fiscal years may not align to calendar years
  </footer>
</body>
</html>"""

    OUT_HTML.write_text(html, encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# 7. MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    sep = "─" * 58
    print(sep)
    print("  US Retail Sector — Financial Analysis & DCF Dashboard")
    print(sep)

    # ── Step 1: Load & clean ──────────────────────────────────────────────
    print("\n[1/5] Loading financials from database...")
    df = load_financials()
    print(f"      {len(df)} company-year rows  ·  "
          f"{df['ticker'].nunique()} companies  ·  "
          f"FY {df['fiscal_year'].min()}–{df['fiscal_year'].max()}")

    # ── Step 2: Ratios ────────────────────────────────────────────────────
    print("\n[2/5] Computing financial ratios...")
    df = compute_ratios(df)
    # Quick sanity print
    latest = df.sort_values("fiscal_year").groupby("ticker").last().reset_index()
    print(latest[["ticker", "GrossMarginPct", "OperatingMarginPct",
                  "NetMarginPct", "CurrentRatio"]].round(2).to_string(index=False))

    # ── Step 3: DCF ───────────────────────────────────────────────────────
    print("\n[3/5] Running simplified DCF model...")
    dcf = compute_dcf(df)
    dcf.to_csv(OUT_CSV, index=False)
    print(f"      DCF table saved → {OUT_CSV}")
    print(dcf[["Ticker", "Company", "Applied Growth (%)",
               "Enterprise Value ($B)"]].to_string(index=False))

    # ── Step 4: MD&A sentiment ────────────────────────────────────────────
    print("\n[4/5] Scoring MD&A sentiment...")
    sdf = load_mda_sentiments()
    if sdf.empty:
        print("      No usable MD&A files found — sentiment charts skipped.")
    else:
        print(f"      Scored {len(sdf)} filings across {sdf['ticker'].nunique()} companies.")
        pivot = sdf.pivot(index="ticker", columns="year", values="sentiment")
        print(pivot.round(2).to_string())

    # ── Step 5: Build report ──────────────────────────────────────────────
    print("\n[5/5] Building interactive HTML report...")
    build_report(df, dcf, sdf)
    print(f"      Report saved → {OUT_HTML.resolve()}")

    print(f"\n{sep}")
    print("  ✓ All done!  Open retail_analysis_report.html in a browser.")
    print(sep)


if __name__ == "__main__":
    main()
