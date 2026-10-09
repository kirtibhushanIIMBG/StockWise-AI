"""Plain-language explanations built from backend-calculated numbers (no LLM needed)."""
import config


def inr(x) -> str:
    return f"₹{x:,.0f}" if float(x).is_integer() else f"₹{x:,.2f}"


def n(x) -> str:
    """Up to 2 decimals, like the dashboard; never scientific (1234567, not 1.23457e+06)."""
    return f"{x:.2f}".rstrip("0").rstrip(".")


def explain_product(r: dict) -> dict:
    name, d, lt = r["product_name"], r["avg_daily_demand"], r["lead_time_days"]
    cov, bo, stock = r["coverage_days"], r["backorders"], r["current_stock"]
    extra = ([f"{n(bo)} already owed to customers"] if bo else []) + (
        [f"plus {n(r['incoming_stock'])} on the way"] if r["incoming_stock"] else [])
    found = (f"You have {n(stock)} units of {name}" + (f" ({'; '.join(extra)})" if extra else "")
             + f" and normally sell about {n(d)} per day.")
    if r["status"] == "Out of Stock":
        why = (f"{name} is out of stock" if stock <= 0 else f"Every unit of {name} on hand is already owed to customers") + (
            f", so every day without stock means missed sales. New stock takes about {n(lt)} days to arrive.")
    elif cov is None:
        why = f"{name} has no regular sales right now, so it ties up money without earning it back."
    elif r["status"] == "Low Demand":
        why = f"{name} sells only about {n(d)} per day, so new stock would tie up money for a long time."
    elif r["shortage_days"] > 0:
        why = (f"Your stock may last only {n(cov)} days, but your supplier normally takes {n(lt)} days. "
               f"That is a possible {n(r['shortage_days'])}-day gap with nothing to sell.")
    elif r["status"] == "Excess Stock":
        why = (f"Stock may last about {n(cov)} days — far more than needed. "
               f"Roughly {inr(r['excess_value'])} of money is tied up in extra stock (an estimate, not cash you can instantly recover).")
    else:
        why = f"Stock may last about {n(cov)} days and the supplier takes {n(lt)} days."
    rop, tgt, calc_rop, calc_tgt = r["reorder_point"], r["target_stock"], r["calc_reorder_point"], r["calc_target_stock"]
    mx = r["max_stock"]
    if mx is not None and mx < rop:
        refill_note = f"; your maximum stock level ({n(mx)}) is below the order point, so we refill to {tgt} units"
    elif tgt < calc_tgt:
        refill_note = f", capped at your maximum stock level: {tgt} units"
    elif tgt > calc_tgt:
        refill_note = f", raised to the order point (your minimum stock level): {tgt} units"
    else:
        refill_note = ""
    if r["suggested_qty"] > 0:
        rec = (f"Place an order now for {r['suggested_qty']} units. This refills you to {tgt} units, "
               + ("adjusted for the stock levels you set." if tgt != calc_tgt else
                  f"enough for the {n(lt)}-day delivery time, a {n(r['review_period_days'])}-day review period and a "
                  f"{n(r['safety_stock'])}-unit buffer."))
        cost = f"{inr(r['estimated_cost'])} at {inr(r['unit_cost'])} per unit."
    else:
        rec = r["action"]
        cost = "No purchase needed."
    assumption = {
        "supplied": "Buffer stock: the value you provided.",
        "statistical": "Buffer stock: calculated from how much daily sales vary (about 95% protection).",
        "default_buffer": "Buffer stock: our default of 2 days of sales, because no buffer was provided.",
    }[r["safety_stock_method"]]
    pos, qty = r["inventory_position"], r["suggested_qty"]
    if r["needs_reorder"]:
        rounded = f", rounded up to {qty}" if n(tgt - pos) != str(qty) else ""
        order = f"Order quantity = {tgt} − {n(pos)} = {n(tgt - pos)}{rounded} units"
    elif r["status"] == "Low Demand":
        order = (f"No order: sales of {n(d)} per day are at or below our low-demand level of "
                 f"{n(config.LOW_DEMAND_THRESHOLD)} per day")
    elif pos > rop:
        order = f"No order: {n(pos)} units is above the order point of {rop}"
    else:  # at a reorder level that is also the refill level
        order = f"No order: {n(pos)} units already reaches the refill level of {tgt}"
    calc = [
        f"Days stock may last = 0: the {n(bo)} units owed to customers use up the {n(stock)} on hand" if stock - bo <= 0 < bo
        else f"Days stock may last = {f'({n(stock)} − {n(bo)} owed)' if bo else n(stock)} ÷ {n(d)} = "
             f"{n(cov) if cov is not None else 'no sales'}",
        f"Order point = {n(d)} per day × {n(lt)} days + {n(r['safety_stock'])} buffer = {calc_rop} units"
        + (f", raised to your minimum stock level: {rop} units" if rop > calc_rop else ""),
        f"Stock available and expected = {n(stock)} + {n(r['incoming_stock'])} incoming − {n(bo)} owed = {n(r['inventory_position'])}",
        f"Refill level = {n(d)} × ({n(lt)} + {n(r['review_period_days'])}) + {n(r['safety_stock'])} = {calc_tgt} units"
        + refill_note,
        order,
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
