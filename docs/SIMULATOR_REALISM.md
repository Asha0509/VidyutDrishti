# Simulator realism check

The detection numbers in the README come from a simulator. To see how far that simulator is from real
meters, its households are compared with real ones.

**Real data:** London Smart Meters (Zenodo 4656091, Monash archive, CC BY 4.0). 1,000 households
(every 5th), one 112-day Monday-aligned window each, half-hourly readings. Households are split by shard:
shard 498 is used to calibrate the simulator, shard 499 only to score it.

**Features (10, scale-free):** cv_daily, ac1, ac7, weekend_ratio, night_share, evening_share,
load_factor, skew_daily, low_day_ratio, intraday_var.

**Scores (held-out shard):** SDMetrics QualityReport, a gradient-boosting classifier trying to tell real from
simulated households (AUC; 0.5 is indistinguishable), and a scaled Wasserstein distance.

| Simulator | Quality | Column shapes | Pair trends | Real-vs-sim AUC | Distance |
|---|---|---|---|---|---|
| Original | 60.9% | 32.4% | 89.4% | 1.00 | 0.902 |
| Calibrated | 83.6% | 76.6% | 90.6% | 0.98 | 0.357 |

Calibration is a random search plus local refinement over eight knobs (`simulator/calibrated_realism.json`,
set via the `realism` config block). With no knobs set the simulator behaves exactly as before.

## What it does not show

* The simulated households are still separable from real ones (AUC 0.98). The simulator is closer, not realistic.
* The real data is London, not Bengaluru feeders; weekend behaviour is not copied; `shape_jitter` sits at its bound.
* There is no real theft data. Theft patterns are still authored.

## Effect on detection

Detection was re-run on the calibrated simulator (`python evals/detection_eval.py --simulator calibrated`).
Development seeds 0-19: precision 0.77, recall 0.84, F1 0.79. Gradual tampering is the weak spot:
recall 0.63, pattern label correct 0.32. An alternative shape classifier (hinge ramp) was tried and was worse
(0.12 pattern accuracy), so it was dropped.
