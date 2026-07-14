"""Builds demo.db (SQLite) with the canonical schema and 26 weeks of seeded,
story-injected data, plus config.demo.yaml wired to it - so anyone can run
the engine end-to-end in under a minute, no ERP required.

Deliberately dirty in realistic ways: a few duplicate order ids, some null
dates, a couple of negative totals - so the data-quality gate has honest work.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3

import numpy as np

RNG = np.random.default_rng(41)
REGIONS = ["Marmara", "Ege", "Ic Anadolu", "Karadeniz", "Akdeniz"]
REGION_W = [0.36, 0.22, 0.18, 0.11, 0.13]
CUSTOMERS = [f"Musteri-{i:02d}" for i in range(1, 21)]
N_ITEMS = 40


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    db_path = os.path.join(here, "demo.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE orders (
          order_id TEXT, order_date TEXT, region TEXT, customer TEXT,
          status TEXT, promised_date TEXT, actual_ship_date TEXT, net_total REAL);
        CREATE TABLE order_lines (order_id TEXT, item_code TEXT, qty REAL);
        CREATE TABLE inventory (item_code TEXT, stock_qty REAL);
        """
    )

    items = [f"ITM-{i:03d}" for i in range(1, N_ITEMS + 1)]
    price = {it: float(RNG.uniform(20, 150)) for it in items}
    today = dt.date.today()
    start = today - dt.timedelta(weeks=27)
    last_week_start = today - dt.timedelta(days=today.weekday() + 7)  # previous full week

    oid = 0
    orders, lines = [], []
    d = start
    while d <= today:
        weekday_factor = 0.3 if d.weekday() == 6 else (0.6 if d.weekday() == 5 else 1.0)
        for region, w in zip(REGIONS, REGION_W):
            spike = region == "Ege" and d >= last_week_start
            lam = 6 * w * weekday_factor * (1.6 if spike else 1.0)
            for _ in range(RNG.poisson(lam)):
                oid += 1
                order_id = f"SO-{oid:06d}"
                customer = CUSTOMERS[int(RNG.integers(0, len(CUSTOMERS)))]
                promised = d + dt.timedelta(days=int(RNG.integers(2, 10)))
                late_p = 0.28 if d >= last_week_start and region == "Karadeniz" else 0.10
                delay = int(RNG.integers(1, 5)) if RNG.random() < late_p else 0
                shipped = promised + dt.timedelta(days=delay - (1 if RNG.random() < 0.4 else 0))
                status = "delivered" if shipped <= today else "open"
                n_lines = int(RNG.integers(1, 5))
                total = 0.0
                for _ in range(n_lines):
                    it = items[int(RNG.integers(0, N_ITEMS))]
                    qty = float(max(1, int(RNG.normal(12, 5))))
                    total += qty * price[it]
                    lines.append((order_id, it, qty))
                orders.append((
                    order_id, d.isoformat(), region, customer, status,
                    promised.isoformat(),
                    shipped.isoformat() if status == "delivered" else None,
                    round(total, 2),
                ))
        d += dt.timedelta(days=1)

    # realistic dirt for the quality gate - dated RECENTLY so the report window sees it
    orders.append(orders[-3])                                   # duplicate order_id
    orders.append(orders[-4])                                   # duplicate order_id
    orders.append(("SO-NEG-01", today.isoformat(), "Ege", "Musteri-02", "open",
                   today.isoformat(), None, -1250.0))           # credit note
    orders.append(("SO-TIME-01", today.isoformat(), "Ege", "Musteri-03", "delivered",
                   today.isoformat(), (today - dt.timedelta(days=3)).isoformat(), 900.0))  # ships before order

    cur.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)", orders)
    cur.executemany("INSERT INTO order_lines VALUES (?,?,?)", lines)

    weekly = {}
    for order_id, it, qty in lines:
        weekly[it] = weekly.get(it, 0) + qty
    inv = []
    for i, it in enumerate(items):
        wk = weekly.get(it, 10) / 26
        cover = RNG.uniform(0.8, 2.0) if i < 5 else RNG.uniform(2.5, 10)
        inv.append((it, round(wk * cover, 1)))
    cur.executemany("INSERT INTO inventory VALUES (?,?)", inv)
    conn.commit()
    conn.close()

    cfg = f"""connection:
  url: sqlite:///{os.path.join(here, 'demo.db').replace(os.sep, '/')}
profile: {os.path.join(root, 'profiles', 'generic.yaml').replace(os.sep, '/')}
report:
  company_alias: "Demo Dagitim A.S."
  lookback_weeks: 13
  low_cover_weeks: 2.0
  out_dir: reports
  state_db: state.db
limits:
  row_cap: 500000
  query_timeout_s: 60
"""
    with open(os.path.join(root, "config.demo.yaml"), "w", encoding="utf-8") as f:
        f.write(cfg)
    print(f"demo.db: {len(orders):,} orders, {len(lines):,} lines, {len(inv)} items -> config.demo.yaml")


if __name__ == "__main__":
    main()
