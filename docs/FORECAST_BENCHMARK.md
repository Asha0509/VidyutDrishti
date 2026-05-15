# Feeder forecast benchmark

**Data:** real London smart meters (same source as `SIMULATOR_REALISM.md`). A feeder is the sum of 50 random real
households, half-hourly. 20 feeders, 28 rolling daily origins each (560 day-ahead forecasts). Nothing is fitted on the
scored days. Reproduce with `python evals/forecast_benchmark.py --chronos tiny,small` (needs torch + chronos-forecasting).

**Metrics:** WAPE (total absolute error / total demand) and MASE (error scaled by a weekly seasonal-naive forecast; below 1
beats it). Lower is better.

| Model | WAPE | MASE |
|---|---|---|
| Chronos-Bolt small (pretrained) | 9.9% | 0.73 |
| Chronos-Bolt tiny (pretrained) | 10.1% | 0.75 |
| **Seasonal mean of last 4 weeks (shipped)** | **11.2%** | **0.83** |
| Yesterday | 13.1% | 0.97 |
| Same slot last week | 13.3% | 0.98 |
| Previous app model (trend + weekly + monthly blend) | 20.5% | 1.52 |

The previous model was the worst of all; it was measured once, before it was replaced (run on half-hourly data, so its
96-slot trend window did not match the data and the gap is probably a little exaggerated).

**Band:** the 10th-90th percentile of the model's own relative errors over the last two weeks. Measured coverage of
actual demand: 78.7% against a nominal 80%.

## Decision

The shipped model is the seasonal mean. Chronos-Bolt is about 10% better on MASE, but it needs PyTorch (hundreds of MB)
and does not fit the 512 MB server. It is available as an opt-in backend (`FORECAST_MODEL=chronos`) that falls back to
the seasonal model if it cannot load. An ONNX export would be the way to ship it; that is not done.

## Limits

* London households aggregated to 50 are not Indian feeders; load shape, weather and outages differ.
* Day-ahead only, no weather or holiday inputs. Indian holidays are not modelled.
