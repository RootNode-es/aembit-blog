import csv
import json
import random

random.seed(42)
CATEGORIES = ["Running", "Football", "Training", "Outdoor", "Lifestyle"]
COLORS = ["Black", "White", "Blue", "Red", "Grey"]

products = [
    {
        "id": f"SKU-{1000 + i}",
        "name": f"{random.choice(['Ultra', 'Pro', 'Flex', 'Aero', 'Core'])} "
                f"{random.choice(['Runner', 'Trainer', 'Boot', 'Jacket', 'Tee'])} {i}",
        "category": random.choice(CATEGORIES),
        "color": random.choice(COLORS),
        "price": round(random.uniform(20, 220), 2),
        "stock": random.randint(0, 500),
    }
    for i in range(100)
]

# CSV
with open("products.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=products[0].keys())
    writer.writeheader()
    writer.writerows(products)

# JSON (pretty-printed, as most APIs and exports deliver it)
with open("products.json", "w") as f:
    json.dump({"products": products}, f, indent=2)

# HTML (a realistic page: styling, classes, wrapper markup)
rows = "\n".join(
    f'      <tr class="product-row" data-sku="{p["id"]}">\n'
    f'        <td class="cell cell-id">{p["id"]}</td>\n'
    f'        <td class="cell cell-name"><a href="/products/{p["id"]}">{p["name"]}</a></td>\n'
    f'        <td class="cell cell-category">{p["category"]}</td>\n'
    f'        <td class="cell cell-color">{p["color"]}</td>\n'
    f'        <td class="cell cell-price"><span class="currency">€</span>{p["price"]}</td>\n'
    f'        <td class="cell cell-stock">{p["stock"]}</td>\n'
    f'      </tr>'
    for p in products
)
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Product Catalog</title>
  <style>
    .catalog-table {{ border-collapse: collapse; width: 100%; font-family: sans-serif; }}
    .cell {{ padding: 8px 12px; border-bottom: 1px solid #ddd; }}
    .product-row:hover {{ background: #f5f5f5; }}
  </style>
</head>
<body>
  <div class="page-wrapper">
    <header class="site-header"><nav class="main-nav"><a href="/">Home</a></nav></header>
    <main class="content">
      <table class="catalog-table">
        <thead>
          <tr><th>ID</th><th>Name</th><th>Category</th><th>Color</th><th>Price</th><th>Stock</th></tr>
        </thead>
        <tbody>
{rows}
        </tbody>
      </table>
    </main>
  </div>
</body>
</html>"""
with open("products.html", "w") as f:
    f.write(html)

print("Wrote products.csv, products.json, products.html")