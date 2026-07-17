"""Builds demo.db (SQLite) with the canonical schema and 26 weeks of seeded,
story-injected data, plus config.demo.yaml wired to it - so anyone can run the
engine end-to-end in under a minute, no ERP required.

Deliberately dirty in realistic ways: a few duplicate order ids, some null
dates, a couple of negative totals - so the data-quality gate has honest work.

Lives inside the package (not a loose script) so ``init-demo`` works from an
installed wheel. The generated config references the bundled ``generic``
profile by name, so no ``profiles/`` folder needs to exist on disk.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import numpy as np

REGIONS = ["Marmara", "Ege", "Ic Anadolu", "Karadeniz", "Akdeniz"]
REGION_W = [0.36, 0.22, 0.18, 0.11, 0.13]
CUSTOMERS = [f"Musteri-{i:02d}" for i in range(1, 21)]
N_ITEMS = 40


def build(target_dir: str | Path | None = None, today: dt.date | None = None) -> Path:
    """Create demo.db + config.demo.yaml in ``target_dir`` (default: cwd).

    ``today`` fixes the anchor date so tests can freeze time; defaults to the
    real current date. Returns the path to the generated config.
    """
    rng = np.random.default_rng(41)
    target = Path(target_dir) if target_dir is not None else Path.cwd()
    target.mkdir(parents=True, exist_ok=True)
    db_path = target / "demo.db"
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE orders (
          order_id TEXT, order_date TEXT, region TEXT, customer TEXT,
          status TEXT, promised_date TEXT, actual_ship_date TEXT, net_total REAL);
        CREATE TABLE order_lines (order_id TEXT, item_code TEXT, qty REAL);
        CREATE TABLE inventory (item_code TEXT, stock_qty REAL);
        CREATE TABLE receivables (
          invoice_id TEXT, customer TEXT, due_date TEXT, open_amount REAL);
        """
    )

    items = [f"ITM-{i:03d}" for i in range(1, N_ITEMS + 1)]
    price = {it: float(rng.uniform(20, 150)) for it in items}
    today = today or dt.date.today()
    start = today - dt.timedelta(weeks=27)
    last_week_start = today - dt.timedelta(days=today.weekday() + 7)  # previous full week

    oid = 0
    orders, lines = [], []
    d = start
    while d <= today:
        weekday_factor = 0.3 if d.weekday() == 6 else (0.6 if d.weekday() == 5 else 1.0)
        for region, w in zip(REGIONS, REGION_W, strict=True):
            spike = region == "Ege" and d >= last_week_start
            lam = 6 * w * weekday_factor * (2.6 if spike else 1.0)
            for _ in range(rng.poisson(lam)):
                oid += 1
                order_id = f"SO-{oid:06d}"
                customer = CUSTOMERS[int(rng.integers(0, len(CUSTOMERS)))]
                promised = d + dt.timedelta(days=int(rng.integers(2, 10)))
                late_p = 0.28 if d >= last_week_start and region == "Karadeniz" else 0.10
                delay = int(rng.integers(1, 5)) if rng.random() < late_p else 0
                shipped = promised + dt.timedelta(days=delay - (1 if rng.random() < 0.4 else 0))
                status = "delivered" if shipped <= today else "open"
                n_lines = int(rng.integers(1, 5))
                total = 0.0
                for _ in range(n_lines):
                    it = items[int(rng.integers(0, N_ITEMS))]
                    qty = float(max(1, int(rng.normal(12, 5))))
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

    weekly: dict[str, float] = {}
    for _order_id, it, qty in lines:
        weekly[it] = weekly.get(it, 0) + qty
    inv = []
    for i, it in enumerate(items):
        wk = weekly.get(it, 10) / 26
        cover = rng.uniform(0.8, 2.0) if i < 5 else rng.uniform(2.5, 10)
        inv.append((it, round(wk * cover, 1)))
    cur.executemany("INSERT INTO inventory VALUES (?,?)", inv)

    # Open receivables with a realistic aging spread (mostly current, a tail of
    # long-overdue), so the aging analysis has all buckets. A few are dirty on
    # purpose (missing due date, a credit balance, a duplicate) - honest work for
    # the receivables quality gate, same as the orders dirt above.
    receivables = []
    inv_id = 0
    for cust in CUSTOMERS:
        for _ in range(int(rng.integers(2, 7))):
            inv_id += 1
            u = rng.random()
            if u < 0.55:
                overdue = int(rng.integers(-30, 10))     # not yet due / just due
            elif u < 0.78:
                overdue = int(rng.integers(10, 40))      # 1-30
            elif u < 0.90:
                overdue = int(rng.integers(40, 70))      # 31-60
            elif u < 0.97:
                overdue = int(rng.integers(70, 100))     # 61-90
            else:
                overdue = int(rng.integers(100, 190))    # 91+
            due = today - dt.timedelta(days=overdue)
            receivables.append((f"INV-{inv_id:05d}", cust, due.isoformat(),
                                round(float(rng.uniform(500, 12000)), 2)))
    receivables.append(("INV-NULLDUE", "Musteri-05", None, 3400.0))          # missing due date
    receivables.append(("INV-CREDIT-1", "Musteri-08", today.isoformat(), -1500.0))  # credit balance
    receivables.append(receivables[0])                                        # duplicate invoice_id
    cur.executemany("INSERT INTO receivables VALUES (?,?,?,?)", receivables)

    conn.commit()
    conn.close()

    db_uri = "sqlite:///" + str(db_path).replace("\\", "/")
    cfg = f"""connection:
  url: {db_uri}
profile: generic
report:
  company_alias: "Demo Dagitim A.S."
  lookback_weeks: 26
  low_cover_weeks: 2.0
  out_dir: reports
  state_db: state.db
limits:
  row_cap: 500000
  query_timeout_s: 60
"""
    cfg_path = target / "config.demo.yaml"
    cfg_path.write_text(cfg, encoding="utf-8")
    print(f"demo.db: {len(orders):,} orders, {len(lines):,} lines, {len(inv)} items, "
          f"{len(receivables):,} receivables -> {cfg_path}")
    return cfg_path


def main() -> None:
    build()


if __name__ == "__main__":
    main()
