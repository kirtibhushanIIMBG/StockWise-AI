from src import config

config.OPENROUTER_API_KEY = config.ANTHROPIC_API_KEY = ""  # unit tests never call a live model

A = dict(sku="A", product_name="Product A", current_stock=20, avg_daily_demand=10, lead_time_days=5,
         safety_stock=10, unit_cost=100, incoming_stock=0, backorders=0)
B = dict(sku="B", product_name="Product B", current_stock=200, avg_daily_demand=5, lead_time_days=4,
         safety_stock=10, unit_cost=80, incoming_stock=0, backorders=0)
C = dict(sku="C", product_name="Product C", current_stock=0, avg_daily_demand=4, lead_time_days=3,
         safety_stock=5, unit_cost=200, incoming_stock=0, backorders=0)
