# Romanian Tax Rules for Investment Portfolio

## Broker Classification (determines tax regime)

The tax rules differ significantly based on broker type:

| Broker Type | Examples | Capital Gains Rate | Loss Offsetting | Dividend Withholding |
|---|---|---|---|---|
| Romanian / Romanian-office | XTB Romania, TradeVille | 3% / 6% | Not allowed | Yes (withheld at source) |
| Foreign (no Romanian office) | IBKR | 16% flat | Allowed | No (self-declare) |

---

## Capital Gains Tax

### Romanian brokers / brokers with office in Romania (XTB, TradeVille)
- **3%** — positions held **>365 days**
- **6%** — positions held **<365 days**
- Losses **cannot** offset gains — each position is taxed independently
- Broker withholds tax at source

### Foreign brokers (IBKR)
- **16%** flat rate regardless of holding period
- Losses **can** offset gains within the same calendar year
- No withholding — investor self-declares via Form 212

### Taxable Base (both broker types)
Gains are calculated **in RON**, not in the original currency:
- Buy price converted to RON at NBR rate on **buy date**
- Sell price converted to RON at NBR rate on **sell date**
- Taxable gain = (sell RON value) − (buy RON value)

**Implication:** Currency movement (e.g. EUR/USD vs RON) is embedded in the taxable gain. A position can show a USD loss but a RON gain if RON depreciated since purchase.

### No Loss Carry-Forward (both broker types)
Losses cannot be carried forward to future tax years regardless of broker.

---

## Dividend Tax (updated 1.1.2026)

### Rate: **16%** for all dividends

### Romanian brokers / brokers with office in Romania (XTB, TradeVille)
- Tax is **withheld at source** by the broker
- Investor must still **declare dividends received** on Form 212
- No extra tax is paid beyond what was withheld — declaration is informational

### Foreign brokers (IBKR)
- No withholding — investor pays 16% via self-declaration on Form 212
- Treaty credits apply: foreign tax already withheld at source (e.g. 10% US withholding via W-8BEN) is credited against the 16% Romanian tax → net 6% additional Romanian tax due for US dividends

### W-8BEN (US stocks)
- Reduces US withholding from 30% → **10%** (Romania-US DTA)
- With Romanian rate now at 16%: 10% credited, **6% additional Romanian tax due**
- Previously (pre-2026 at 8%): no additional Romanian tax was due — **this has changed**

---

## Social Contributions on Investment Income

### CASS (Health Insurance — 10%)
Applies if total net investment income (capital gains + dividends + interest) exceeds **6× the gross minimum wage** in that year.
- Minimum wage: 4,050 RON (Jan–Jun 2026) → **4,325 RON from July 2026**
- 2025 threshold: 6 × 4,050 = **24,300 RON**
- 2026 blended threshold ≈ 6 × ((4,050 × 6 + 4,325 × 6) / 12) ≈ **25,125 RON**
- From 2027 threshold (if wage stays at 4,325): 6 × 4,325 = **25,950 RON**
- CASS applies only on the **threshold amount** (6× min wage), not on the full income
- Effectively a fixed ~2,595 RON/year extra cost once threshold is crossed

### CAS (Pension — 25%)
**Does not apply** to investment income.

---

## Romanian Government Bonds (TradeVille)

- Interest income: **0% tax** for individuals (tax-exempt by law)
- Capital gains on early sale: **0% tax** for individuals
- Most tax-efficient instrument — no income tax, no dividend tax, no capital gains

---

## ANAF Declaration (Form 212)

- **What:** Foreign-source income AND Romanian-source dividends (even if withheld)
- **Deadline:** May 25 of the following year (e.g., 2025 income → May 25, 2026)
- **Currency:** All amounts reported in RON using official NBR exchange rates on transaction dates
- **Payment:** Tax due at time of filing

---

## ETF-Specific Rules

### Accumulating ETFs (most UCITS ETFs on XTB)
- No dividend tax event while accumulating — distributions reinvested inside the fund
- Tax deferred until sale; taxed as capital gain (3% or 6% via XTB)
- **More tax-efficient** than distributing ETFs — avoids the 16% dividend tax on distributions

### Distributing ETFs
- Distributions taxed as dividends at 16%
- Capital gain on price appreciation taxed separately at sale

---

## Practical Decision Rules for Analysis

1. **Hold past 365 days (XTB/TradeVille positions):** Halves the capital gains rate from 6% → 3%. **CRITICAL: This rule only applies to positions with a capital gain (profit > 0). For positions at a loss, there is zero tax regardless of holding period — the 365-day threshold is completely irrelevant and must NOT be cited as a reason to hold a losing position.**

2. **Loss harvesting (XTB/TradeVille):** Not applicable — losses cannot offset gains at these brokers. Do not recommend selling losers to offset winners.

3. **Loss harvesting (IBKR):** Valid within the same calendar year only (no carry-forward). Flag in Q4 if applicable.

4. **Dividend stocks:** Now taxed at 16% — prefer accumulating ETFs or non-dividend stocks for tax efficiency.

5. **W-8BEN dividend impact (post-2026):** US dividends now carry a net 6% Romanian tax on top of the 10% US withholding. Factor this into yield comparisons.

6. **Bond position:** Tax-free income — do not penalize vs equities without adjusting for tax. Gross yield on bonds equals net yield.

7. **Currency impact:** Always compute both USD/EUR P&L and RON P&L — the RON figure is what matters for tax. RON depreciation inflates the taxable gain.
