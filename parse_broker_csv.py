"""
Parses broker CSV exports and stores transactions in investment_income.db.
Supports XTB stock format. Run whenever a new quarterly CSV is dropped in utils/taxes/.

Usage:
    python parse_broker_csv.py utils/taxes/2026/q1_xtb_stocks.csv
    python parse_broker_csv.py utils/taxes/2026/  # parse all CSVs in a folder
"""

import csv
import sqlite3
import sys
import os
import re
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "utils" / "taxes" / "2026" / "investment_income.db"


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id            TEXT PRIMARY KEY,
            broker        TEXT NOT NULL,
            type          TEXT NOT NULL,   -- 'dividend' | 'sell_profit' | 'tax_ro' | 'withholding_tax'
            date          TEXT NOT NULL,
            ticker        TEXT,
            currency      TEXT,
            gross         REAL,
            tax_withheld  REAL,
            net           REAL,
            comment       TEXT,
            year          INTEGER,
            quarter       INTEGER,
            source_file   TEXT
        )
    """)
    conn.commit()


def quarter_from_date(date_str):
    month = datetime.fromisoformat(date_str[:10]).month
    return (month - 1) // 3 + 1


def year_from_date(date_str):
    return int(date_str[:4])


MONTHS_RO = {
    "ianuarie": "01", "februarie": "02", "martie": "03",
    "aprilie": "04", "mai": "05", "iunie": "06",
    "iulie": "07", "august": "08", "septembrie": "09",
    "octombrie": "10", "noiembrie": "11", "decembrie": "12",
}


def parse_ron_number(s):
    """Convert Romanian number string '1.234,56' or '9,39' to float."""
    return float(s.strip().replace(".", "").replace(",", "."))


def parse_ro_date(s):
    """Convert '31 martie 2026' to '2026-03-31'."""
    day, month_ro, year = s.strip().split()
    return f"{year}-{MONTHS_RO[month_ro.lower()]}-{int(day):02d}"


def parse_ing_lei_csv(filepath):
    """
    Parses ING Bank RON transaction exports.
    Only extracts 'Actualizare dobanda' (deposit interest) events.

    ING CSV structure: Titular, Fisier sursa, Data, Detalii tranzactie, Debit, Credit
    Each interest event spans 4 rows:
      row 1: date | 'Actualizare dobanda' | | gross_credit
      row 2:     | 'Data: DD-MM-YYYY'
      row 3:     | 'Principal:X,XX'
      row 4:     | 'Impozit pe dobanda:X,XX'
    """
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    records = []
    i = 0
    while i < len(rows):
        row = rows[i]
        if len(row) < 6:
            i += 1
            continue

        source_file = row[1].strip()
        date_str = row[2].strip()
        detail = row[3].strip()
        credit_str = row[5].strip()

        if detail == "Actualizare dobanda" and date_str and credit_str:
            try:
                date_iso = parse_ro_date(date_str)
                net = parse_ron_number(credit_str)  # Credit = Principal = net after tax
            except (ValueError, KeyError):
                i += 1
                continue

            tax = 0.0
            j = i + 1
            while j < len(rows) and j <= i + 4:
                next_detail = rows[j][3].strip() if len(rows[j]) > 3 else ""
                if next_detail.startswith("Impozit pe dobanda:"):
                    tax = parse_ron_number(next_detail.split(":")[1])
                j += 1

            gross = round(net + tax, 2)  # gross = Principal + Impozit

            source_ts = source_file.replace("Tranzactii_", "").replace(".csv", "")
            amount_key = f"{net:.2f}".replace(".", "_")
            tx_id = f"ING-{source_ts}-{date_iso}-{amount_key}"

            records.append({
                "id": tx_id,
                "broker": "ING",
                "type": "interest",
                "date": f"{date_iso} 00:00:00",
                "ticker": None,
                "currency": "RON",
                "gross": gross,
                "tax_withheld": tax,
                "net": net,
                "comment": "Dobanda depozit",
                "year": int(date_iso[:4]),
                "quarter": quarter_from_date(date_iso),
                "source_file": str(filepath),
            })

        i += 1

    return records


def parse_tradeville_csv(filepath):
    """
    Parses Tradeville broker CSV exports (EUR or RON accounts).
    Extracts taxable events only:
      - 'div'  → dividend / bond coupon income
      - 'vanz' → sell (realized gain/loss)

    Tradeville CSV columns:
      Cont, Moneda, Data, Oper, Ticker, Pret, Cantitate, Comision,
      Valoare Net, Profit/Pierdere, Impozit, Taxa Piata, Observatii / Nrtz

    Date format: MM/DD/YY HH:MM:SS
    """
    def parse_tv_date(s):
        # '03/19/26 14:11:01' → '2026-03-19 14:11:01'
        date_part, time_part = s.strip().split()
        m, d, y = date_part.split("/")
        year = f"20{y}"
        return f"{year}-{m}-{d} {time_part}"

    def safe_float(s):
        s = s.strip()
        return float(s) if s else 0.0

    records = []
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            oper = row["Oper"].strip().lower()
            if oper not in ("div", "vanz"):
                continue

            currency = row["Moneda"].strip()
            date_iso = parse_tv_date(row["Data"])
            valoare_net = safe_float(row["Valoare Net"])
            profit = safe_float(row["Profit/Pierdere"])
            impozit = safe_float(row["Impozit"])
            observatii = row["Observatii / Nrtz"].strip()

            # Ticker: use column value; if it equals currency (bond case), extract from comment
            ticker = row["Ticker"].strip()
            if ticker == currency and observatii:
                ticker = observatii.split()[-1]

            account = row["Cont"].strip()
            tx_id = f"TV-{account}-{date_iso.replace(' ', 'T')}-{oper}-{abs(valoare_net):.2f}"

            if oper == "div":
                gross = valoare_net
                records.append({
                    "id": tx_id,
                    "broker": "Tradeville",
                    "type": "dividend",
                    "date": date_iso,
                    "ticker": ticker,
                    "currency": currency,
                    "gross": gross,
                    "tax_withheld": impozit,
                    "net": round(gross - impozit, 2),
                    "comment": observatii,
                    "year": year_from_date(date_iso),
                    "quarter": quarter_from_date(date_iso),
                    "source_file": str(filepath),
                })

            elif oper == "vanz":
                records.append({
                    "id": tx_id,
                    "broker": "Tradeville",
                    "type": "sell_profit",
                    "date": date_iso,
                    "ticker": ticker,
                    "currency": currency,
                    "gross": profit,
                    "tax_withheld": impozit,
                    "net": round(profit - impozit, 2),
                    "comment": observatii,
                    "year": year_from_date(date_iso),
                    "quarter": quarter_from_date(date_iso),
                    "source_file": str(filepath),
                })

    return records


def parse_xtb_csv(filepath):
    """
    Parses any XTB transaction CSV export (stocks USD or ETFs EUR account).
    Returns (rows, currency) where currency is read from the account header row.

    XTB CSV structure (after skipping header rows):
      col1(ignored), ID, Type, Time, Comment, Symbol, Amount
    """
    rows = []
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        raw = list(reader)

    # Read account currency from row index 1, column 5
    currency = "USD"
    if len(raw) > 1 and len(raw[1]) > 5:
        detected = raw[1][5].strip()
        if detected in ("USD", "EUR", "GBP", "PLN"):
            currency = detected

    # Find the data header row ("ID" in column 1)
    data_start = None
    for i, row in enumerate(raw):
        if len(row) > 1 and row[1].strip() == "ID":
            data_start = i + 1
            break

    if data_start is None:
        raise ValueError(f"Could not find data header row in {filepath}")

    for row in raw[data_start:]:
        if len(row) < 7:
            continue
        tx_id = row[1].strip()
        if not tx_id or tx_id.lower() == "total":
            break

        tx_type = row[2].strip()
        date = row[3].strip()
        comment = row[4].strip()
        symbol = row[5].strip() if row[5].strip() else None
        try:
            amount = float(row[6].strip()) if row[6].strip() else 0.0
        except ValueError:
            continue

        rows.append({
            "raw_id": tx_id,
            "raw_type": tx_type,
            "date": date,
            "comment": comment,
            "symbol": symbol,
            "amount": amount,
        })

    return rows, currency


def normalize_xtb_rows(raw_rows, source_file, broker="XTB", currency="USD"):
    """
    Converts raw XTB rows into normalized transaction records.

    XTB records sell events as two paired rows:
      - 'close trade'  → profit/loss amount
      - 'Stock sale'   → gross proceeds

    Dividends come as:
      - 'DIVIDENT'       → gross amount
      - 'Withholding Tax'→ tax (negative)

    tax_ro rows record Romanian tax paid by XTB on our behalf.
    """
    normalized = []

    # Index by raw_id for pairing
    by_id = {r["raw_id"]: r for r in raw_rows}
    used = set()

    # Group dividends by (symbol, date minute) to pair gross + withholding
    div_groups = {}
    for r in raw_rows:
        if r["raw_type"].upper() == "DIVIDENT":
            key = (r["symbol"], r["date"][:16])
            div_groups.setdefault(key, []).append(r)

    wht_groups = {}
    for r in raw_rows:
        if r["raw_type"].lower() == "withholding tax":
            key = (r["symbol"], r["date"][:16])
            wht_groups.setdefault(key, []).append(r)

    # --- Dividends ---
    for key, divs in div_groups.items():
        whts = wht_groups.get(key, [])
        for i, div in enumerate(divs):
            gross = div["amount"]
            wht = whts[i]["amount"] if i < len(whts) else 0.0
            net = gross + wht  # wht is negative
            normalized.append({
                "id": f"DIV-{div['raw_id']}",
                "broker": broker,
                "type": "dividend",
                "date": div["date"][:19],
                "ticker": div["symbol"],
                "currency": currency,
                "gross": gross,
                "tax_withheld": abs(wht),
                "net": net,
                "comment": div["comment"],
                "year": year_from_date(div["date"]),
                "quarter": quarter_from_date(div["date"]),
                "source_file": source_file,
            })
            used.add(div["raw_id"])
            if i < len(whts):
                wht_row = whts[i]
                normalized.append({
                    "id": f"WHT-{wht_row['raw_id']}",
                    "broker": broker,
                    "type": "withholding_tax",
                    "date": wht_row["date"][:19],
                    "ticker": wht_row["symbol"],
                    "currency": currency,
                    "gross": 0.0,
                    "tax_withheld": abs(wht_row["amount"]),
                    "net": wht_row["amount"],
                    "comment": wht_row["comment"],
                    "year": year_from_date(wht_row["date"]),
                    "quarter": quarter_from_date(wht_row["date"]),
                    "source_file": source_file,
                })
                used.add(wht_row["raw_id"])

    # --- Sell profits: pair 'close trade' with its 'Stock sale' ---
    # They share the same timestamp and symbol; IDs are consecutive
    close_trades = [r for r in raw_rows if r["raw_type"].lower() == "close trade"]
    stock_sales = {r["raw_id"]: r for r in raw_rows if r["raw_type"].lower() == "stock sale"}

    for ct in close_trades:
        if ct["raw_id"] in used:
            continue
        profit = ct["amount"]
        # Find matching stock sale: same symbol + same minute timestamp
        sale = None
        for sid, sr in stock_sales.items():
            if sid in used:
                continue
            if sr["symbol"] == ct["symbol"] and sr["date"][:16] == ct["date"][:16]:
                sale = sr
                break

        gross_proceeds = sale["amount"] if sale else None
        normalized.append({
            "id": f"SELL-{ct['raw_id']}",
            "broker": broker,
            "type": "sell_profit",
            "date": ct["date"][:19],
            "ticker": ct["symbol"],
            "currency": currency,
            "gross": profit,           # profit before Romanian tax
            "tax_withheld": 0.0,       # RO tax tracked separately as tax_ro rows
            "net": profit,
            "comment": ct["comment"],
            "year": year_from_date(ct["date"]),
            "quarter": quarter_from_date(ct["date"]),
            "source_file": source_file,
        })
        used.add(ct["raw_id"])
        if sale:
            used.add(sale["raw_id"])

    # --- Romanian tax rows ---
    for r in raw_rows:
        if r["raw_type"].lower() == "tax ro" and r["raw_id"] not in used:
            normalized.append({
                "id": f"TAXRO-{r['raw_id']}",
                "broker": broker,
                "type": "tax_ro",
                "date": r["date"][:19],
                "ticker": r["symbol"],
                "currency": currency,
                "gross": 0.0,
                "tax_withheld": abs(r["amount"]),
                "net": r["amount"],
                "comment": r["comment"],
                "year": year_from_date(r["date"]),
                "quarter": quarter_from_date(r["date"]),
                "source_file": source_file,
            })
            used.add(r["raw_id"])

    # --- Free-funds interest ---
    for r in raw_rows:
        if r["raw_type"].lower() == "free-funds interest" and r["raw_id"] not in used:
            normalized.append({
                "id": f"INT-{r['raw_id']}",
                "broker": broker,
                "type": "interest",
                "date": r["date"][:19],
                "ticker": None,
                "currency": currency,
                "gross": r["amount"],
                "tax_withheld": 0.0,
                "net": r["amount"],
                "comment": r["comment"],
                "year": year_from_date(r["date"]),
                "quarter": quarter_from_date(r["date"]),
                "source_file": source_file,
            })
            used.add(r["raw_id"])

    return normalized


def insert_transactions(conn, records):
    inserted = 0
    skipped = 0
    for r in records:
        try:
            conn.execute("""
                INSERT INTO transactions
                    (id, broker, type, date, ticker, currency, gross,
                     tax_withheld, net, comment, year, quarter, source_file)
                VALUES
                    (:id, :broker, :type, :date, :ticker, :currency, :gross,
                     :tax_withheld, :net, :comment, :year, :quarter, :source_file)
            """, r)
            inserted += 1
        except sqlite3.IntegrityError:
            skipped += 1
    conn.commit()
    return inserted, skipped


def print_summary(conn, year=None):
    year_filter = f"AND year = {year}" if year else ""

    print("\n=== INVESTMENT INCOME SUMMARY ===")
    if year:
        print(f"Year: {year}")

    # Get all currencies present in the DB for this year
    cur = conn.execute(f"""
        SELECT DISTINCT currency FROM transactions
        WHERE type IN ('dividend', 'sell_profit', 'tax_ro', 'interest') {year_filter}
        ORDER BY currency
    """)
    currencies = [r[0] for r in cur.fetchall()]

    for ccy in currencies:
        ccy_filter = f"{year_filter} AND currency = '{ccy}'"

        print(f"\n{'='*10} {ccy} {'='*10}")

        # Dividends
        cur = conn.execute(f"""
            SELECT quarter, ticker,
                   SUM(gross) as gross,
                   SUM(tax_withheld) as withheld,
                   SUM(net) as net
            FROM transactions
            WHERE type = 'dividend' {ccy_filter}
            GROUP BY quarter, ticker
            ORDER BY quarter, ticker
        """)
        rows = cur.fetchall()
        if rows:
            ro_gov_bond = re.compile(r'^R\d{4}[A-Z]{2}$')
            taxable = [(q, t, g, w, n) for q, t, g, w, n in rows if not ro_gov_bond.match(t or "")]
            exempt  = [(q, t, g, w, n) for q, t, g, w, n in rows if ro_gov_bond.match(t or "")]

            print(f"\n  --- Dividends ---")
            current_q = None
            q_gross = q_withheld = q_net = 0
            total_gross = total_withheld = total_net = 0
            for q, ticker, gross, withheld, net in taxable:
                if current_q != q:
                    if current_q is not None:
                        print(f"  Q{current_q} subtotal: gross={q_gross:.2f}  withheld={q_withheld:.2f}  net={q_net:.2f}")
                    current_q = q
                    q_gross = q_withheld = q_net = 0
                    print(f"\n  Q{q}:")
                print(f"    {ticker:<12}  gross={gross:>7.2f}  withheld={withheld:>6.2f}  net={net:>7.2f}")
                q_gross += gross; q_withheld += withheld; q_net += net
                total_gross += gross; total_withheld += withheld; total_net += net
            if taxable:
                print(f"  Q{current_q} subtotal: gross={q_gross:.2f}  withheld={q_withheld:.2f}  net={q_net:.2f}")
                print(f"\n  TOTAL DIVIDENDS: gross={total_gross:.2f}  withheld={total_withheld:.2f}  net={total_net:.2f}  ({ccy})")

            if exempt:
                print(f"\n  --- Romanian Gov Bonds (tax-exempt) ---")
                for q, ticker, gross, withheld, net in exempt:
                    print(f"    Q{q}  {ticker:<12}  coupon={gross:>7.2f}  ({ccy})  [not taxed]")

        # Sell profits
        cur = conn.execute(f"""
            SELECT quarter, ticker, SUM(gross) as profit
            FROM transactions
            WHERE type = 'sell_profit' {ccy_filter}
            GROUP BY quarter, ticker
            ORDER BY quarter, ticker
        """)
        rows = cur.fetchall()
        if rows:
            print(f"\n  --- Realized Gains ---")
            current_q = None
            q_total = grand_total = 0
            for row in rows:
                q, ticker, profit = row
                if current_q != q:
                    if current_q is not None:
                        print(f"  Q{current_q} subtotal: {q_total:.2f}")
                    current_q = q
                    q_total = 0
                    print(f"\n  Q{q}:")
                print(f"    {ticker:<12}  profit={profit:>8.2f}")
                q_total += profit; grand_total += profit
            print(f"  Q{current_q} subtotal: {q_total:.2f}")

            cur2 = conn.execute(f"""
                SELECT SUM(tax_withheld)
                FROM transactions
                WHERE type = 'tax_ro' {ccy_filter}
            """)
            ro_tax = cur2.fetchone()[0] or 0.0
            print(f"\n  TOTAL REALIZED GAINS (gross): {grand_total:.2f}  ({ccy})")
            print(f"  Romanian tax paid:            {ro_tax:.2f}  ({ccy})")
            print(f"  TOTAL REALIZED GAINS (net):   {grand_total - ro_tax:.2f}  ({ccy})")

        # Interest
        cur = conn.execute(f"""
            SELECT quarter, SUM(gross) as gross, SUM(tax_withheld) as tax, SUM(net) as net
            FROM transactions
            WHERE type = 'interest' {ccy_filter}
            GROUP BY quarter
            ORDER BY quarter
        """)
        rows = cur.fetchall()
        if rows:
            print(f"\n  --- Interest ---")
            total_gross = total_tax = total_net = 0
            for q, gross, tax, net in rows:
                if tax:
                    print(f"    Q{q}: gross={gross:.2f}  tax={tax:.2f}  net={net:.2f}")
                else:
                    print(f"    Q{q}: {net:.2f}")
                total_gross += gross; total_tax += tax; total_net += net
            if total_tax:
                print(f"\n  TOTAL INTEREST: gross={total_gross:.2f}  tax={total_tax:.2f}  net={total_net:.2f}  ({ccy})")
            else:
                print(f"\n  TOTAL INTEREST: {total_net:.2f}  ({ccy})")

    print()


def get_ytd_summary(conn, year):
    """Returns a dict with YTD totals per currency — used by portfolio_analysis.py."""
    ro_gov_bond = re.compile(r'^R\d{4}[A-Z]{2}$')

    cur = conn.execute("""
        SELECT DISTINCT currency FROM transactions
        WHERE type IN ('dividend', 'sell_profit', 'tax_ro', 'interest')
        AND year = ?
        ORDER BY currency
    """, (year,))
    currencies = [r[0] for r in cur.fetchall()]

    by_currency = {}
    for ccy in currencies:
        # Dividends (taxable only — exclude RO gov bonds)
        cur = conn.execute("""
            SELECT ticker, quarter,
                   SUM(gross), SUM(tax_withheld), SUM(net)
            FROM transactions
            WHERE type = 'dividend' AND currency = ? AND year = ?
            GROUP BY ticker, quarter
            ORDER BY quarter, ticker
        """, (ccy, year))
        div_rows = cur.fetchall()

        taxable_divs = [(t, q, g, w, n) for t, q, g, w, n in div_rows if not ro_gov_bond.match(t or "")]
        exempt_divs  = [(t, q, g, w, n) for t, q, g, w, n in div_rows if ro_gov_bond.match(t or "")]

        div_gross  = round(sum(g for _, _, g, _, _ in taxable_divs), 2)
        div_wht    = round(sum(w for _, _, _, w, _ in taxable_divs), 2)
        div_net    = round(sum(n for _, _, _, _, n in taxable_divs), 2)

        exempt_total = round(sum(g for _, _, g, _, _ in exempt_divs), 2)

        # Realized gains
        cur = conn.execute("""
            SELECT quarter, ticker, SUM(gross)
            FROM transactions
            WHERE type = 'sell_profit' AND currency = ? AND year = ?
            GROUP BY quarter, ticker
            ORDER BY quarter
        """, (ccy, year))
        gain_rows = cur.fetchall()
        gain_gross = round(sum(g for _, _, g in gain_rows), 2)

        cur = conn.execute("""
            SELECT SUM(tax_withheld) FROM transactions
            WHERE type = 'tax_ro' AND currency = ? AND year = ?
        """, (ccy, year))
        ro_tax = round(cur.fetchone()[0] or 0.0, 2)

        # Interest
        cur = conn.execute("""
            SELECT quarter, SUM(gross), SUM(tax_withheld), SUM(net)
            FROM transactions
            WHERE type = 'interest' AND currency = ? AND year = ?
            GROUP BY quarter
            ORDER BY quarter
        """, (ccy, year))
        int_rows = cur.fetchall()
        int_gross = round(sum(g for _, g, _, _ in int_rows), 2)
        int_tax   = round(sum(t for _, _, t, _ in int_rows), 2)
        int_net   = round(sum(n for _, _, _, n in int_rows), 2)

        # Interest by broker
        cur = conn.execute("""
            SELECT broker, SUM(gross), SUM(tax_withheld), SUM(net)
            FROM transactions
            WHERE type = 'interest' AND currency = ? AND year = ?
            GROUP BY broker
            ORDER BY broker
        """, (ccy, year))
        int_by_broker = {row[0]: {"gross": round(row[1], 2), "tax": round(row[2], 2), "net": round(row[3], 2)}
                         for row in cur.fetchall()}

        # Per-quarter breakdown
        quarters = {}
        all_quarters = sorted(set(
            [q for _, q, _, _, _ in taxable_divs] +
            [q for q, _, _ in gain_rows] +
            [q for q, _, _, _ in int_rows]
        ))
        for q in all_quarters:
            quarters[f"Q{q}"] = {
                "dividend_net": round(sum(n for _, qq, _, _, n in taxable_divs if qq == q), 2),
                "realized_gain_gross": round(sum(g for qq, _, g in gain_rows if qq == q), 2),
                "interest_net": round(sum(n for qq, _, _, n in int_rows if qq == q), 2),
            }

        by_currency[ccy] = {
            "dividends": {"gross": div_gross, "tax_withheld": div_wht, "net": div_net},
            "ro_gov_bonds_exempt": {"total_coupons": exempt_total},
            "realized_gains": {"gross": gain_gross, "ro_tax_paid": ro_tax, "net": round(gain_gross - ro_tax, 2)},
            "interest": {"gross": int_gross, "tax_withheld": int_tax, "net": int_net, "by_broker": int_by_broker},
            "by_quarter": quarters,
        }

    return {"year": year, "by_currency": by_currency}


def process_file(filepath):
    filepath = Path(filepath)
    if not filepath.exists():
        print(f"ERROR: file not found: {filepath}")
        return

    fname = filepath.name.lower()
    if "xtb" in fname:
        broker = "XTB"
        raw, currency = parse_xtb_csv(filepath)
        records = normalize_xtb_rows(raw, str(filepath), broker=broker, currency=currency)
    elif "ing" in fname:
        records = parse_ing_lei_csv(filepath)
    elif "tradeville" in fname:
        records = parse_tradeville_csv(filepath)
    else:
        print(f"WARNING: unrecognized broker format for {filepath.name}, skipping.")
        return

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    inserted, skipped = insert_transactions(conn, records)
    print(f"{filepath.name}: {inserted} new records inserted, {skipped} already existed.")

    # Print summary for the year inferred from filename or data
    years = {r["year"] for r in records}
    for year in sorted(years):
        print_summary(conn, year)
    conn.close()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--summary":
        if not DB_PATH.exists():
            print("No investment_income.db found. Run the script with a CSV file first.")
            sys.exit(1)
        conn = sqlite3.connect(DB_PATH)
        init_db(conn)
        if len(sys.argv) >= 3:
            years = [int(sys.argv[2])]
        else:
            cur = conn.execute("SELECT DISTINCT year FROM transactions ORDER BY year")
            years = [r[0] for r in cur.fetchall()]
        for year in years:
            print_summary(conn, year)
        conn.close()
        return

    target = Path(sys.argv[1])
    if target.is_dir():
        csv_files = sorted(target.glob("*.csv"))
        if not csv_files:
            print(f"No CSV files found in {target}")
            sys.exit(1)
        for f in csv_files:
            process_file(f)
    else:
        process_file(target)


if __name__ == "__main__":
    main()
