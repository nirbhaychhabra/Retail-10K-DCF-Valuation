# US Retail Sector — Automated SEC 10-K Data Pipeline, Multi-Stage DCF Valuation & MD&A NLP Sentiment Engine

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://github.com/nirbhaychhabra/Retail-10K-DCF-Valuation)
[![SQLite](https://img.shields.io/badge/Database-SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://github.com/nirbhaychhabra/Retail-10K-DCF-Valuation)
[![SEC EDGAR API](https://img.shields.io/badge/Data-SEC%20EDGAR%20API-darkgreen?style=for-the-badge)](https://github.com/nirbhaychhabra/Retail-10K-DCF-Valuation)
[![Plotly](https://img.shields.io/badge/Interactive-Plotly%20Dashboard-3F4F75?style=for-the-badge&logo=plotly&logoColor=white)](https://nirbhaychhabra.github.io/Retail-10K-DCF-Valuation/)
[![Valuation](https://img.shields.io/badge/Financial%20Modeling-DCF%20%26%20Gordon%20Growth-gold?style=for-the-badge)](https://github.com/nirbhaychhabra/Retail-10K-DCF-Valuation)

**Author:** Nirbhay Chhabra  
*Luther College — Double Major in Accounting & Data Science (150-Credit CPA Track | Class of 2028)*  
[LinkedIn Profile](https://www.linkedin.com/in/nirbhay-chhabra232) • [GitHub Profile](https://github.com/nirbhaychhabra) • **[Live Interactive Dashboard](https://nirbhaychhabra.github.io/Retail-10K-DCF-Valuation/)**

---

## 📌 Executive Summary

This end-to-end quantitative financial analytics project bridges **US GAAP corporate accounting**, **automated data engineering**, and **equity valuation modeling**. 

The system builds an automated pipeline querying the **SEC EDGAR API** to extract 5 years of audited **Form 10-K filings** and qualitative **Item 7 Management’s Discussion and Analysis (MD&A)** disclosures across **10 major US retail corporations**. It populates a normalized relational database (720+ financial observations), calculates DuPont ratios and liquidity trends via SQL, forecasts multi-year Net Operating Profit After Tax (NOPAT), computes **Discounted Cash Flow (DCF)** Enterprise Values using the Gordon Growth model, and runs a financial lexicon NLP engine analyzing 45+ MD&A reports.

The final output is an interactive, standalone **Plotly HTML dashboard** synthesizing quantitative valuations with qualitative management sentiment.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         SYSTEM ARCHITECTURE PIPELINE                             │
└──────────────────────────────────────────────────────────────────────────────────┘
   [ SEC EDGAR API ] (SEC Company Facts & Filing Indexes)
           │
           ├──► fetch_financials.py ──► XBRL Tag Harmonization ──► retail_financials.db (SQLite)
           │                                                                   │
           └──► fetch_mda_text.py   ──► Item 7 HTML/iXBRL Parser ──► mda_texts/*.txt
                                                                               │
                                    ┌──────────────────────────────────────────┘
                                    ▼
                              analyze.py
   ┌────────────────────────────────┼────────────────────────────────┐
   ▼                                ▼                                ▼
[ Ratio & Growth Engine ]     [ 5-Yr DCF Model ]            [ MD&A NLP Sentiment ]
• Revenues & 5-Yr CAGR        • NOPAT = EBIT * (1 - t)      • Loughran-McDonald Lexicon
• Gross & Operating Margins   • Discounting via WACC (9.0%) • Bullish vs. Cautionary Words
• Current & Quick Ratios      • Terminal Value (g = 2.5%)   • Net Sentiment Trend / Heatmap
   └────────────────────────────────┬────────────────────────────────┘
                                    ▼
                retail_analysis_report.html (Plotly Dashboard)
                 [Hosted Live via GitHub Pages as index.html]
```

---

## 🏢 Target Retail Universe

The pipeline evaluates 10 leading public retailers across general merchandise, warehouse clubs, off-price retail, and department stores:

| Ticker | Company | Sub-Industry | CIK |
| :---: | :--- | :--- | :---: |
| **WMT** | Walmart Inc. | Hypermarkets & Supercenters | `0000104169` |
| **COST** | Costco Wholesale Corp. | Membership Warehouse Clubs | `0000909832` |
| **TGT** | Target Corporation | General Merchandise | `0000027419` |
| **TJX** | The TJX Companies, Inc. | Off-Price Apparel & Home | `0000109198` |
| **ROST** | Ross Stores, Inc. | Off-Price Apparel | `0000745732` |
| **DG** | Dollar General Corporation | Discount Retail | `0000029534` |
| **DLTR** | Dollar Tree, Inc. | Discount Retail | `0000935703` |
| **BBY** | Best Buy Co., Inc. | Consumer Electronics | `0000764478` |
| **M** | Macy's, Inc. | Department Stores | `0000794367` |
| **KSS** | Kohl's Corporation | Department Stores | `0000852830` |

---

## 💰 DCF Valuation Methodology & Key Findings

### Model Parameters & Assumptions
- **Weighted Average Cost of Capital (WACC):** `9.0%`
- **Long-Run Terminal Growth Rate ($g$):** `2.5%` (benchmarked to long-run nominal US GDP growth)
- **Effective Tax Rate:** `21.0%` (US federal statutory rate)
- **Projection Horizon:** `5 Years`
- **NOPAT Formula:** $\text{NOPAT} = \text{Operating Income (EBIT)} \times (1 - \text{Tax Rate})$
- **Terminal Value (Gordon Growth Model):**
  $$\text{TV} = \frac{\text{FCF}_5 \times (1 + g)}{\text{WACC} - g}$$
  $$\text{PV}(\text{TV}) = \frac{\text{TV}}{(1 + \text{WACC})^5}$$
- **Enterprise Value ($\text{EV}$):**
  $$\text{Enterprise Value} = \sum_{t=1}^{5} \frac{\text{FCF}_t}{(1 + \text{WACC})^t} + \text{PV}(\text{TV})$$

### Valuation Results Summary Table

| Ticker | Company | NOPAT Base ($B) | Hist. CAGR (%) | Applied Growth (%) | PV of FCFs ($B) | Terminal Value ($B) | **Enterprise Value ($B)** |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **WMT** | Walmart | $23.56 | +3.5% | +3.5% | $101.27 | $287.48 | **$388.75 B** |
| **COST** | Costco | $9.23 | +10.7% | +10.7% | $48.30 | $156.98 | **$205.28 B** |
| **TGT** | Target | $4.51 | -13.9% | -5.0% | $15.21 | $35.75 | **$50.96 B** |
| **ROST** | Ross Stores | $2.14 | +4.7% | +4.7% | $9.50 | $27.59 | **$37.09 B** |
| **DG** | Dollar General | $1.93 | -11.7% | -5.0% | $6.52 | $15.33 | **$21.85 B** |
| **DLTR** | Dollar Tree | $1.40 | -7.4% | -5.0% | $4.73 | $11.12 | **$15.85 B** |
| **BBY** | Best Buy | $1.24 | -15.2% | -5.0% | $4.19 | $9.86 | **$14.06 B** |
| **M** | Macy's | $0.81 | +3.0% | +3.0% | $3.44 | $9.67 | **$13.11 B** |
| **KSS** | Kohl's | $0.57 | -24.7% | -5.0% | $1.91 | $4.49 | **$6.40 B** |

*Note: Historical CAGR outliers are bounded within [-5.0%, +20.0%] to ensure defensible, conservative valuation horizons.*

---

## 📝 Qualitative MD&A Sentiment Analysis (NLP Engine)

Beyond pure financial ratios, this engine processes Item 7 MD&A textual disclosures across **45+ filings** using a curated financial lexicon (based on the Loughran-McDonald financial dictionary):
- **Bullish Indicators:** *growth, expansion, outpaced, robust, momentum, profitability, demand, efficiency, record*.
- **Cautionary Indicators:** *headwinds, pressure, inflation, shrinkage, impairment, volatility, tariffs, supply chain disruption*.
- **Net Sentiment Metric:**
  $$\text{Net Sentiment Score} = \frac{\text{Bullish Count} - \text{Cautionary Count}}{\text{Total Word Count}} \times 1,000$$

### Key NLP Insights
- **Costco (COST) & Walmart (WMT):** Maintained persistently positive net sentiment scores (+12 to +18 per 1k words), highlighting membership renewal strength and supply chain scale advantages.
- **Department Stores (Kohl's, Macy's):** Displayed escalating cautionary frequencies regarding discretionary merchandise softness, inventory markdowns, and consumer debt pressure.

---

## 💻 Tech Stack & Engineering Details

- **Programming:** Python 3.10+ (`pandas`, `numpy`, `sqlite3`, `requests`, `beautifulsoup4`, `plotly`)
- **Database:** SQLite relational architecture with automated deduplication across overlapping XBRL filing facts
- **Web Scraping & APIs:** SEC EDGAR REST API with custom User-Agent compliance, SEC CIK resolution, and multi-document fallback extraction
- **Visualization:** Self-contained Plotly HTML interactive charts (heatmaps, line charts, scatter plots, bar charts)
- **Deployment:** GitHub Pages live deployment (`index.html`)

---

## 🚀 How to Run Locally

### 1. Clone the Repository
```bash
git clone https://github.com/nirbhaychhabra/Retail-10K-DCF-Valuation.git
cd Retail-10K-DCF-Valuation
```

### 2. Install Dependencies
```bash
pip install pandas numpy plotly requests beautifulsoup4
```

### 3. Run Pipeline Scripts
```bash
# 1. Fetch audited XBRL financial statements from SEC EDGAR
python fetch_financials.py

# 2. Extract Item 7 MD&A textual sections
python fetch_mda_text.py

# 3. Compute ratios, run DCF models, score sentiment, and build interactive report
python analyze.py
```

### 4. View Report
Open `retail_analysis_report.html` (or `index.html`) in any modern web browser to explore interactive charts and tables.

---

## 📁 Repository Structure

```text
├── analyze.py                   # Master analysis engine (ratios, DCF modeling, sentiment scoring, Plotly report)
├── fetch_financials.py          # SEC EDGAR XBRL API data ingestion pipeline
├── fetch_mda_text.py            # Item 7 MD&A text extraction & HTML/iXBRL cleaner
├── retail_financials.db         # SQLite database storing 720+ multi-year GAAP observations
├── dcf_summary.csv              # Exported summary table of DCF Enterprise Values and assumptions
├── retail_analysis_report.html  # Interactive self-contained Plotly HTML dashboard
├── index.html                   # Root entry point for GitHub Pages hosting
├── mda_texts/                   # Downloaded raw Item 7 text files across tickers and years
└── README.md                    # Comprehensive technical documentation & methodology
```

---

## 📬 Contact & Inquiries
- **Author:** Nirbhay Chhabra
- **Email:** nirbhaychhabra1@gmail.com
- **LinkedIn:** [linkedin.com/in/nirbhay-chhabra232](https://www.linkedin.com/in/nirbhay-chhabra232)
- **GitHub:** [github.com/nirbhaychhabra](https://github.com/nirbhaychhabra)
