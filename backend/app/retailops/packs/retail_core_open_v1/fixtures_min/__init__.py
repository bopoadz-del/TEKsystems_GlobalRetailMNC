"""Minimal committed FreshRetailNet-shaped pilot rows (deterministic subset demo).

These are synthetic rows matching the FreshRetailNet column semantics for
offline tests and as a fallback when the HF download is unavailable. They are
NOT the public dataset itself — licence/authority records still require live
acquire when network is available.
"""

# 3 stores x 3 products x 5 days — deterministic and tiny.
MINI_FRESH_ROWS = [
    {
        "city_id": 1,
        "store_id": sid,
        "management_group_id": 1,
        "first_category_id": 10,
        "second_category_id": 20,
        "third_category_id": 30,
        "product_id": pid,
        "dt": dt,
        "sale_amount": float((sid + pid) % 7) + 0.5 * day,
        "stock_hour6_22_cnt": (sid + pid + day) % 5,
        "discount": 0.9 if day % 2 == 0 else 1.0,
        "holiday_flag": 1 if day == 0 else 0,
        "activity_flag": 1 if day % 2 == 0 else 0,
        "precpt": 0.0,
        "avg_temperature": 22.0,
        "avg_humidity": 60.0,
        "avg_wind_level": 2.0,
    }
    for sid in (1, 2, 3)
    for pid in (101, 202, 303)
    for day, dt in enumerate(
        ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    )
]

MINI_UCI_ROWS = [
    {
        "Invoice": "536365",
        "StockCode": "85123A",
        "Description": "WHITE HANGING HEART T-LIGHT HOLDER",
        "Quantity": 6,
        "InvoiceDate": "2010-12-01 08:26:00",
        "UnitPrice": 2.55,
        "CustomerID": "17850",
        "Country": "United Kingdom",
    },
    {
        "Invoice": "C536379",
        "StockCode": "D",
        "Description": "Discount",
        "Quantity": -1,
        "InvoiceDate": "2010-12-01 09:41:00",
        "UnitPrice": 27.5,
        "CustomerID": "14527",
        "Country": "United Kingdom",
    },
    {
        "Invoice": "536366",
        "StockCode": "22633",
        "Description": "HAND WARMER UNION JACK",
        "Quantity": 6,
        "InvoiceDate": "2010-12-01 08:28:00",
        "UnitPrice": 1.85,
        "CustomerID": "17850",
        "Country": "United Kingdom",
    },
]
