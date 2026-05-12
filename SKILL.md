# Portfolio Analysis Assistant

## Investor Profile
- Age: 29, Bucharest Romania, single, no kids
- Income: €45k/year (top 1-5% Romania), average-high risk tolerance
- Brokers: XTB (EUR/USD), TradeVille (RON) — both Romanian or Romania-registered
- W-8BEN filed
- Base currency: EUR

## Romanian Tax Rules
- Capital gains tax: 3% if position held >365 days, 6% if <365 days
- Dividends/gains must be declared in "Declaratia Unica" even if broker withholds tax
- US dividends: 15% withholding (W-8BEN reduces from 30%)

## Portfolio Structure

### 1. ETFs — XTB, EUR
Monthly investment: €1,000–2,000. Goal: hold 10–15+ years.
Target allocation: S&P 500 30% | STOXX Europe 600 20% | Global REIT 15% | Canada 10% | EM 10% | Bonds 10% | Small Cap 5%

### 2. Individual Stocks — XTB, USD
No regular investment. US market only. Growth focus, no dividends preferred.
- SELL (waiting for >365 days for 3% tax rate): PTC, OSPN, OTEX, LULU
- HOLD/GROW: AMZN, ADBE

### 3. Romania — TradeVille, RON
- BET ETF: €250 RON/month, hold 10–15 years
- Romanian Government Bonds: inflation hedge for uncommitted cash

## Analysis Instructions
Output a complete self-contained HTML report titled "portfolio-analysis-{{TODAY}}" with dark financial dashboard aesthetic and inline CSS.

Cover all sections concisely using tables over prose:
1. Portfolio overview — total value in EUR, allocation breakdown
2. ETF portfolio — holdings vs target allocation
3. Individual stocks — each position: days held, tax rate (3%/6%), buy/sell/hold
4. Romania portfolio — BET ETF and bonds
5. Tax notes — positions >365 days, estimated capital gains tax impact
6. Global news — macro events affecting the portfolio
7. Stock-specific news — per ticker
8. Romania news — political/economic developments
9. Watchlist & alerts — opportunities and risks based on current news
