"""Generates data/sample_sales.csv: ~2 years of realistic sales transactions.

Run directly: python data/seed_data.py
"""

import os
import random

import numpy as np
import pandas as pd
from faker import Faker

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "sample_sales.csv")

REGIONS = ["North America", "Europe", "Asia Pacific", "Latin America", "Middle East & Africa"]
CATEGORIES = {
    "Electronics": (80, 1200),
    "Home & Garden": (15, 400),
    "Apparel": (10, 150),
    "Sporting Goods": (20, 500),
    "Office Supplies": (5, 200),
}
CHANNELS = ["Online", "Retail Store", "Partner Reseller"]


def generate(n_rows: int = 6000, seed: int = 42) -> pd.DataFrame:
    fake = Faker()
    Faker.seed(seed)
    random.seed(seed)
    np.random.seed(seed)

    dates = pd.date_range("2024-01-01", "2025-12-31", freq="D")
    # Weight recent quarters slightly higher so "last quarter" questions have signal.
    date_weights = np.linspace(0.6, 1.4, len(dates))
    date_weights /= date_weights.sum()

    rows = []
    for i in range(n_rows):
        order_date = np.random.choice(dates, p=date_weights)
        region = random.choice(REGIONS)
        category = random.choice(list(CATEGORIES.keys()))
        low, high = CATEGORIES[category]
        unit_price = round(random.uniform(low, high), 2)
        units = random.randint(1, 12)
        discount_pct = random.choice([0, 0, 0, 5, 10, 15, 20])
        revenue = round(unit_price * units * (1 - discount_pct / 100), 2)
        rows.append(
            {
                "order_id": 100000 + i,
                "order_date": pd.Timestamp(order_date).date(),
                "region": region,
                "product_category": category,
                "sales_channel": random.choice(CHANNELS),
                "customer_name": fake.name(),
                "units_sold": units,
                "unit_price": unit_price,
                "discount_pct": discount_pct,
                "revenue": revenue,
            }
        )

    df = pd.DataFrame(rows).sort_values("order_date").reset_index(drop=True)
    return df


if __name__ == "__main__":
    df = generate()
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"Wrote {len(df)} rows to {OUTPUT_PATH}")
