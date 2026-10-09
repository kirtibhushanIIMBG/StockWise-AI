# StockWise AI: Business Case

## Who it is for
**Persona:** the owner / purchase manager of a Rs 5-10 crore a year FMCG distributor or multi-store retailer in a tier-2 Indian city (Nagpur, Indore, Coimbatore, Surat). About 1,000 products, 2-3 suppliers per category, stock tracked in Excel or Tally, reorders decided from memory and a weekly walk of the shelves.

**Problem:** two costly mistakes, every week.
1. **Stock-outs.** A product runs out before the supplier delivers; the sale goes to the shop next door.
2. **Cash tied up.** Safety stock is a gut-feel "keep 15 days"; it is too high for steady products and too low for volatile ones.

Both come from one weak input: demand is treated as a flat average, so weekends, festivals and promotions are invisible.

## What StockWise changes
- Reads the manager's own spreadsheet and says what to order, how many units, what it costs, and why.
- Spends a limited budget in priority order, never above it.
- **New: a demand forecast** (weekday, trend, promotion and Diwali effects) that sets safety stock from the model's *measured* error instead of a rule of thumb.

## Measured model results (synthetic demo data, `models/metrics.json`)
These are measured on 24 products x 730 days of **synthetic** sales, scored on the last 56 days that the model never saw during tuning.

| Measure | Flat average (today) | ML forecast | Change |
|---|---|---|---|
| Holdout MAE (units/day) | 3.19 | 3.06 | 4.1% lower |
| Holdout WAPE | 40.4% | 38.7% | |
| Safety stock, 24 demo products | Rs 48,570 (361 units) | Rs 46,690 (345 units) | 3.9% less cash tied up |

The gain over the flat average is real but modest (the synthetic noise is large); the gain over "repeat last week" is 28.2%. We do not claim more than this. The pilot below is how a real customer would confirm it.

## ROI model
**Every input below is an assumption** for the persona, not a measurement. Change them and the totals change.

| Input | Value |
|---|---|
| Annual revenue | Rs 7.5 crore (Rs 7,50,00,000) |
| Inventory value at cost | Rs 1.2 crore (Rs 1,20,00,000) |
| Safety stock as share of inventory | 20% (Rs 24,00,000) |
| Carrying cost of capital and storage | 18% a year |
| Revenue lost to stock-outs today | 4% of revenue (Rs 30,00,000) |
| Gross margin | 18% |
| Reduction in stock-out loss from better forecasts | 10% (assumption; the measured 4.1% error gain makes this plausible but it needs a pilot to confirm) |
| Manager time on reorder decisions | 10 hours a week; StockWise saves half |
| Manager hourly cost | Rs 500 |

**Formulas and results**
- (a) Working capital freed = safety-stock value x measured reduction = Rs 24,00,000 x 3.87% = **Rs 92,897**. Annual saving = freed x 18% = **Rs 16,721**.
- (b) Lost-sales margin recovered = revenue x stock-out loss x reduction x margin = Rs 7,50,00,000 x 4% x 10% x 18% = **Rs 54,000**.
- (c) Time saved = 5 hours x 52 weeks x Rs 500 = **Rs 1,30,000**.
- **Total annual benefit = Rs 2,00,721 (about Rs 16,727 a month).**

Honest reading: roughly two thirds of the benefit is time saved by the deterministic reorder and budget tools; the ML forecast mainly adds (a) and part of (b). Even with the forecast benefit set to zero, the tool pays back.

## Pricing (Rs per month, by catalogue size)
| Tier | SKUs | Price |
|---|---|---|
| Starter | up to 200 | Rs 999 |
| Growth | up to 1,500 | Rs 2,499 |
| Scale | up to 5,000 | Rs 5,999 |

**Payback for the persona (Growth tier):** annual price Rs 29,988 / monthly benefit Rs 16,727 = **about 1.8 months**.

## Go-to-market
1. **Distributor associations** (FMCG distributor and retailer bodies): a 30-minute WhatsApp-recorded demo using the members' own CSV.
2. **Tally / ERP partners:** they already export stock and sales CSVs; StockWise reads almost any CSV, so integration is a file drop, not a project.
3. **WhatsApp-led demos:** a 3-minute screen recording of "upload sheet, see what to order with Rs 25,000".
4. **Pilot to paid:** 30-day free pilot on one category; compare stock-outs and cash tied up with the previous 30 days; convert on the numbers.

## Risks and caveats
- **Synthetic data.** All model figures come from generated demo history. Real sales are noisier or smoother; a pilot must re-run `python -m src.model` on the customer's file before any claim.
- **Small accuracy gain.** If real demand is mostly random, the forecast adds little over the average; the product still delivers the reorder, budget and explanation value.
- **Cold start.** Products with under 28 days of history cannot be forecast and fall back to the flat average.
- **Trust.** Mitigated by showing the formula behind every number and checking every AI-written figure against the calculations.
- **AI cost and limits.** The forecast and all calculations run without any AI key; only the chat and describe-your-stock features need one.
