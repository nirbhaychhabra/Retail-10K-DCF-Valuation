import json
import sqlite3
import time
import datetime
import requests

EMAIL = "nirbhaychhabra1@gmail.com"
HEADERS = {"user-agent": f"Student Research Project - {EMAIL}"}

COMPANIES = {
    "WMT": "Walmart",
    "TGT": "Target",
    "COST": "Costco",
    "TJX": "TJX Companies",
    "DG": "Dollar General",
    "ROST": "Ross Stores",
    "BBY": "Best Buy",
    "KSS": "Kohl's",
    "DLTR": "Dollar Tree",
    "M": "Macy's",
}

# XBRL tag  →  canonical column name stored in DB.
# Multiple tags may map to the same canonical name; we keep the highest value
# found per (ticker, fiscal_year) so gaps are filled across filing styles.
METRICS = {
    # ── Revenue (retailers use several different tags) ───────────────────
    "Revenues":                                         "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "Revenues",
    "RevenueFromContractWithCustomerIncludingAssessedTax": "Revenues",
    "SalesRevenueNet":                                  "Revenues",
    "SalesRevenueGoodsNet":                             "Revenues",
    # ── Income statement ─────────────────────────────────────────────────
    "GrossProfit":                                      "GrossProfit",
    "CostOfGoodsAndServicesSold":                       "CostOfGoodsAndServicesSold",
    "OperatingIncomeLoss":                              "OperatingIncomeLoss",
    "NetIncomeLoss":                                    "NetIncomeLoss",
    # ── Balance sheet ────────────────────────────────────────────────────
    "Assets":                                           "Assets",
    "AssetsCurrent":                                    "AssetsCurrent",
    "Liabilities":                                      "Liabilities",
    "LiabilitiesCurrent":                               "LiabilitiesCurrent",
    "StockholdersEquity":                               "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": "StockholdersEquity",
    "CashAndCashEquivalentsAtCarryingValue":            "CashAndCashEquivalentsAtCarryingValue",
    "InventoryNet":                                     "InventoryNet",
    # ── Cash-flow proxies ────────────────────────────────────────────────
    "DepreciationDepletionAndAmortization":             "DDA",
    "PaymentsToAcquirePropertyPlantAndEquipment":       "CapEx",
}

# Only keep the last N fiscal years of data
YEARS_BACK = 5
DB_PATH = "retail_financials.db"


def get_ticker_to_cik_map():
    """SEC EDGAR requires a numeric CIK, not a ticker, for lookups."""
    url = "https://www.sec.gov/files/company_tickers.json"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    data = resp.json()

    ticker_map = {}
    for entry in data.values():
        ticker_map[entry["ticker"].upper()] = str(entry["cik_str"]).zfill(10)
    return ticker_map


def get_company_facts(cik):
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code != 200:
        print(f"  Warning: failed to fetch CIK {cik} (status {resp.status_code})")
        return None
    return resp.json()


def extract_annual_metrics(facts_json, ticker):
    """
    companyfacts JSON nests data as:
    facts -> us-gaap -> <tag> -> units -> USD -> [ {val, fy, fp, form, ...}, ... ]
    We want form == '10-K' (annual) entries only, filtered to the last YEARS_BACK fiscal years.

    Multiple XBRL tags may map to the same canonical column (e.g. several revenue
    tag variants all -> 'Revenues').  We keep the LARGEST absolute value per
    (canonical_name, fiscal_year) so the total-revenue line wins over sub-segments.
    """
    rows = []
    if not facts_json or "us-gaap" not in facts_json.get("facts", {}):
        return rows

    gaap = facts_json["facts"]["us-gaap"]

    current_year = datetime.date.today().year
    cutoff_year  = current_year - YEARS_BACK

    # key = (canonical_name, fiscal_year)  ->  dict with entry + val
    best: dict = {}

    for xbrl_tag, canonical_name in METRICS.items():
        if xbrl_tag not in gaap:
            continue
        units = gaap[xbrl_tag].get("units", {}).get("USD", [])
        for entry in units:
            if entry.get("form") != "10-K" or entry.get("fp") != "FY":
                continue
            fy = entry.get("fy")
            if fy is None or fy <= cutoff_year:
                continue

            key = (canonical_name, fy)
            val = entry.get("val") or 0

            if key not in best:
                best[key] = {"entry": entry, "canonical": canonical_name, "val": val}
            else:
                prev = best[key]
                # Keep larger |value| — picks total-company revenue over a sub-segment
                if abs(val) > abs(prev["val"]):
                    best[key] = {"entry": entry, "canonical": canonical_name, "val": val}
                elif abs(val) == abs(prev["val"]) and entry.get("filed","") > prev["entry"].get("filed",""):
                    best[key] = {"entry": entry, "canonical": canonical_name, "val": val}

    for (canonical_name, fy), rec in best.items():
        entry = rec["entry"]
        rows.append({
            "ticker":      ticker,
            "metric":      canonical_name,
            "fiscal_year": fy,
            "value":       rec["val"],
            "filed":       entry.get("filed"),
            "start":       entry.get("start"),
            "end":         entry.get("end"),
        })

    return rows


def setup_database(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS financials (
            ticker TEXT,
            metric TEXT,
            fiscal_year INTEGER,
            value REAL,
            filed TEXT,
            period_start TEXT,
            period_end TEXT,
            UNIQUE(ticker, metric, fiscal_year, period_end)
        )
    """)
    conn.commit()


def insert_rows(conn, rows):
    conn.executemany("""
        INSERT OR REPLACE INTO financials
        (ticker, metric, fiscal_year, value, filed, period_start, period_end)
        VALUES (:ticker, :metric, :fiscal_year, :value, :filed, :start, :end)
    """, rows)
    conn.commit()


def main():
    if "your_email" in EMAIL:
        print("!! Update the EMAIL variable at the top of this script before running.")
        print("   SEC EDGAR will reject requests without a real contact email.")
        return

    current_year = datetime.date.today().year
    cutoff_year = current_year - YEARS_BACK
    print(f"Pulling last {YEARS_BACK} fiscal years (FY > {cutoff_year})...")
    print(f"Companies: {len(COMPANIES)}")
    print("Fetching ticker -> CIK mapping...")
    ticker_map = get_ticker_to_cik_map()

    conn = sqlite3.connect(DB_PATH)
    setup_database(conn)

    for ticker, name in COMPANIES.items():
        cik = ticker_map.get(ticker)
        if not cik:
            print(f"  Could not find CIK for {ticker} ({name}) -- skipping")
            continue

        print(f"Fetching {name} ({ticker}), CIK {cik}...")
        facts = get_company_facts(cik)
        rows = extract_annual_metrics(facts, ticker)
        insert_rows(conn, rows)
        print(f"  Stored {len(rows)} data points across {YEARS_BACK} years")

        # SEC asks for no more than ~10 requests/second; this is well under that
        time.sleep(0.3)

    conn.close()
    print(f"\nDone. Data saved to {DB_PATH}")
    print("Next: run a quick check with sqlite3 or pandas to confirm the data looks right.")


if __name__ == "__main__":
    main()
