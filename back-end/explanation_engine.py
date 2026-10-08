"""Plain-language explanations built from backend-calculated numbers (no LLM needed)."""


def inr(x) -> str:
    return f"₹{x:,.0f}" if float(x).is_integer() else f"₹{x:,.2f}"


def n(x) -> str:
    return f"{x:g}"


def explain_product(r: dict) -> dict:
    name, d, lt = r["product_name"], r["avg_daily_demand"], r["lead_time_days"]
    cov = r["coverage_days"]
    found = (f"You have {n(r['current_stock'])} units of {name}"
             + (f" (plus {n(r['incoming_stock'])} on the way)" if r["incoming_stock"] else "")
             + f" and normally sell about {n(d)} per day.")
    if r["status"] == "Out of Stock":
        why = f"{name} is out of stock, so every day without stock means missed sales. New stock takes about {n(lt)} days to arrive."
    elif cov is None:
        why = f"{name} has no regular sales right now, so it ties up money without earning it back."
    elif r["shortage_days"] > 0:
        why = (f"Your stock may last only {n(cov)} days, but your supplier normally takes {n(lt)} days. "
               f"That is a possible {n(r['shortage_days'])}-day gap with nothing to sell.")
    elif r["status"] == "Excess Stock":
        why = (f"Stock may last about {n(cov)} days — far more than needed. "
               f"Roughly {inr(r['excess_value'])} of money is tied up in extra stock (an estimate, not cash you can instantly recover).")
    else:
        why = f"Stock may last about {n(cov)} days and the supplier takes {n(lt)} days."
    if r["suggested_qty"] > 0:
        rec = (f"Place an order now for {r['suggested_qty']} units. This refills you to {r['target_stock']} units, "
               f"enough for the {n(lt)}-day delivery time, a {n(r['review_period_days'])}-day review period and a "
               f"{n(r['safety_stock'])}-unit buffer.")
        cost = f"{inr(r['estimated_cost'])} at {inr(r['unit_cost'])} per unit."
    else:
        rec = r["action"]
        cost = "No purchase needed."
    assumption = {
        "supplied": "Buffer stock: the value you provided.",
        "statistical": "Buffer stock: calculated from how much daily sales vary (about 95% protection).",
        "default_buffer": "Buffer stock: our default of 2 days of sales, because no buffer was provided.",
    }[r["safety_stock_method"]]
    calc = [
        f"Days stock may last = {n(r['current_stock'])} ÷ {n(d)} = {n(cov) if cov is not None else 'no sales'}",
        f"Order point = {n(d)} per day × {n(lt)} days + {n(r['safety_stock'])} buffer = {r['reorder_point']} units",
        f"Stock available and expected = {n(r['current_stock'])} + {n(r['incoming_stock'])} incoming − {n(r['backorders'])} owed = {n(r['inventory_position'])}",
        f"Refill level = {n(d)} × ({n(lt)} + {n(r['review_period_days'])}) + {n(r['safety_stock'])} = {r['target_stock']} units",
        f"Order quantity = {r['target_stock']} − {n(r['inventory_position'])} = {r['suggested_qty']} units" if r["needs_reorder"]
        else f"No order: {n(r['inventory_position'])} units is above the order point of {r['reorder_point']}",
        assumption,
    ]
    return {"what_we_found": found, "why_it_matters": why, "what_we_recommend": rec,
            "estimated_cost": cost, "how_calculated": calc}


def explain_plan(p: dict) -> str:
    full = [l for l in p["lines"] if l["funding"] == "Full"]
    part = [l for l in p["lines"] if l["funding"] == "Partial"]
    if not p["lines"]:
        return "Nothing needs to be ordered right now."
    if p["units_unfunded"] == 0:
        return f"Your budget covers everything we recommend. You'll spend {inr(p['total_spend'])} and keep {inr(p['remaining_budget'])}."
    msg = "Your budget is not enough to purchase all recommended items. Here is what you can afford. "
    if full:
        msg += f"It fully covers {', '.join(l['product_name'] for l in full[:5])}{'…' if len(full) > 5 else ''}. "
    for l in part:
        msg += f"{l['product_name']} gets {l['buy_qty']} units but still needs another {l['unfunded_qty']}. "
    msg += f"Buying everything would cost {inr(p['total_required_cost'])}."
    return msg
