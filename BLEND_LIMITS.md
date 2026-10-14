# Charge-mix limits (`state["blend_limits"]`)

Standing limits on each furnace's charge mix, plus the group's monthly local scrap supply. The
optimizer applies them by default; a run can override them (`run_constraints.blend_limits`). The
engine's `blend_within_limits` check warns, without blocking, when a stored blend sits outside its
limits.

None of the four workbooks carries a range. Only New Corp Model v8 has blend data at all, and it
holds single points: 80/80/80/80% DRI on four lines and 20% on ESR. The matrix below is therefore
built from three layers of evidence.

**Source tags:**
- **[W]** the workbook;
- **[E]** Ezz's own CARES-verified EPD;
- **[L]** the metallurgical literature;
- **[A]** an assumption that needs the plant's figures.

## Limits, % of solid charge

| Furnace | DRI min | DRI max | Local scrap max | Imported scrap max | Today (DRI/local/imp.) |
|---|---:|---:|---:|---:|---|
| EZDK long | 65 [A] | 95 [L] | 25 [A] | 30 [A] | 80 / 4 / 16 |
| EFS long | 65 [A] | 95 [L] | 25 [A] | 30 [A] | 80 / 14 / 6 |
| ESR long | 0 | 30 [W, L] | 40 [A] | 100 | 20 / 16 / 64 |
| EZDK flat | 70 [E] | 95 [L] | 25 [A] | 20 [L] | 80 / 17 / 3 |
| EFS flat | 70 [A] | 95 [L] | 25 [A] | 20 [L] | 80 / 14 / 6 |

Scrap minimums are 0%. Every line is within its limits today.

**Group local scrap supply: 82 kt/month [A].** That is about 1.5× today's group use. A first draft
said 50 kt, from "33 kt bought today", but 33 kt is the long lines only; the flat lines use another
20.2 kt. Today's group use is therefore 54.8 kt, and a 50 kt cap would have put the current plan
above what the market can supply.

**Group DRI ≤ 408 kt/month [W]** (3.0 + 1.9 Mt/y). This is not a separate limit: it equals the
existing DRI capacity ceilings, EZDK 250,000 t + ERM 158,333 t, which the optimizer already enforces.

## Why these values

- **DRI 65–95% on the integrated lines.**
  - Ezz's EPD reports recycled content of 29.3% for rebar and 19.3% for HRC, i.e. roughly 70–80%
    DRI in practice; EZDK flat's 70% minimum comes from there.
  - Heats at 95–98% DRI are run industrially with continuous feeding.
  - The 65% minimums on the long lines are an assumption.
- **ESR ≤ 30% DRI.** ESR has no reduction plant: it buys DRI and charges by bucket, and bucket
  charging suits up to 25–30% DRI.
- **Imported scrap ≤ 20% on flat lines.** Copper: exposed flat products need about 0.06–0.08% Cu,
  and obsolete scrap carries about 0.3%. Rebar tolerates up to 0.50% Cu, hence 30% on the long
  lines.
- **Local scrap.** The Egyptian scrap market is thin, hence 25% per line and the group supply cap.

Sources: [Ezz Steel CARES EPD](https://www.ezzsteel.com/downloads/212/CC13119BK%20CARES%20SCS%20Scheme%20BRE%20verified%20EPD%20Long%20&%20Flat%20Products.pdf) ·
[IspatGuru – DRI in EAF](https://www.ispatguru.com/use-of-direct-reduced-iron-in-electric-arc-furnace/) ·
[Midrex – The Versatile OBM](https://www.midrex.com/direct-from-midrex/technical-articles/the-versatile-obm-ore-based-metallic-part-1-everything-you-ever-wanted-to-know-about-direct-reduced-iron-but-were-afraid-to-ask/) ·
[steelonthenet – Copper ceiling](https://www.steelonthenet.com/insights/copper-ceiling-scrap-circularity.html)

## What the limits do to the optimum (dummy baseline, HRC market 120 kt)

| | Group CM, M$/month |
|---|---:|
| Today's plan | 35.59 |
| Optimum without limits | 65.62 (blends go to 100% of one material) |
| **Optimum with these limits** | **51.97** |
| Sales and sourcing only (blends held) | 45.41 |

With the limits, the LP takes DRI *down* to its minimum on most lines, even where scrap costs more
than DRI. EZDK's DRI capacity binds, at $74 per extra ton, so DRI is worth more making extra steel
than replacing scrap.

## Open questions only the plant can answer

1. The actual minimum and maximum DRI share each melt shop has run (this replaces the [A] minimums
   and maximums).
2. How much local scrap purchasing can really source per month (this replaces the 82 kt).
3. Whether ESR's 20% DRI is a cost choice or a feeding limit.

## Not adopted (yet)

- **Extra electricity per DRI point** (about +14.5 kWh/t per +10 points of DRI, ≈ $1/t). The
  workbook's EAF power is a fixed kWh per ton. Adding this term only to the optimizer would make it
  disagree with the engine, and the engine cross-check would then refuse every answer. It has to
  be a model change: power rising with DRI share above a reference blend. That keeps the LP exact
  (the term is linear in charge tons), but it changes today's cost figures, so it is your call.
- **EZDK's local scrap price** (300 $/t on the long line, 248.87 $/t on the flat line). The same
  company paying two prices for the same material looks like an error, but the direction is
  unclear:
  - 300 is a round number, typed for both local and imported scrap, and copied to ESR;
  - 248.87 is EFS's local price on both of EFS's lines.

  The optimum *with limits* depends on it, and the optimum without limits barely does: setting EZDK
  flat to 300 still leaves 34.7 → 62.4 M$. **Which price is right?**
