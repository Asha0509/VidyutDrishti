# VidyutDrishti

**Electricity-theft detection for a distribution network.** VidyutDrishti compares the energy each transformer sends out with what its customers' meters record, checks every meter against its own history and its neighbours, and gives field teams an inspection list ranked by rupees at stake, with the evidence behind every flag.

> Prototype on synthetic data. No integration with real AMI, SCADA, MDM or billing systems, and no real consumer data.

## The problem

Indian distribution companies lose a large share of the energy they buy to aggregate technical and commercial (AT&C) losses, and theft is a big part of the commercial side. Smart meters report every 15 minutes, but inspection teams are small, so the question is not "is anything wrong?" but **"which few meters should someone visit tomorrow?"** A flag is only useful if it is usually right, comes with a reason an inspector can check, and is ordered by how much money a visit is likely to recover.

## Results (measured, on networks the detector never saw)

The simulator records every theft it injects and every legitimate drop (a vacant house), so each flag can be checked meter by meter. Thresholds were tuned on development seeds 0-19 only; the numbers below are the mean over **20 held-out random networks** (seeds 1000-1019, 8 transformers × 6 meters, 60 days, 11 random thefts and 4 vacancy decoys each).

| Metric | Held-out mean (range) |
|---|---|
| Precision: flagged meters that were thefts | **0.82** (0.71-0.92) |
| Recall: thefts that were flagged | **0.93** (0.82-1.00) |
| F1 | **0.87** (0.78-0.96) |
| Precision of the top 10 in the queue | 0.85 |
| Recall by kind: meter stopped / hook bypass / gradual tampering | 0.98 / 0.97 / 0.78 |
| Vacant-house decoys still flagged | 54% |

On the fixed demo network the detector finds all 14 thefts with 2 false alarms (both vacant houses), on average 7.9 days after the theft starts. Treat that one as optimistic: it is the network the scoring was developed on.

**What doesn't work well yet:** vacant houses look like theft at first (half are still flagged), so every flag goes through an inspection brief and a field check before anyone is accused. Gradual tampering is caught 78% of the time but is rarely labelled as gradual.

Reproduce: `python evals/detection_eval.py` (writes `evals/results/detection.json`; CI fails if held-out recall drops below the gate).

## How a meter gets flagged

Four independent checks run every day for every meter. No single one flags a meter on its own.

| Layer | What it checks |
|---|---|
| **L0 Transformer balance** | Share of transformer input that no meter recorded, last 7 days vs the 14 before. If it rose by more than the noise floor, a subset search finds which meters' drops explain the extra missing energy. Too small to see means "inconclusive", not "fine". |
| **L1 Own history** | Last 7 days vs the meter's own 14-day baseline (z-score), plus a separate 3-week trend test that catches step-by-step tampering. |
| **L2 Neighbours** | The drop relative to the median of the other meters on the same transformer, so weather and holidays cancel out. |
| **L3 Outlier model** | Isolation forest over drop ratio, gap to neighbours, zero-usage days and trend. Adds weight only. |

The layers combine into a confidence score. A meter is flagged at **0.50** and tiered HIGH (≥ 0.80), MEDIUM (≥ 0.65) or REVIEW (≥ 0.50). The queue is ordered by estimated monthly loss: drop × 30 days × tariff (₹6 domestic, ₹8 industrial, ₹9 commercial per kWh, assumed) × confidence. A pattern label (flat at zero, sudden drop, gradual decline) comes from fitting a step vs a ramp.

## AI features

Detection is deterministic and unit-tested. Language models sit on top to explain and summarise; they never decide whether a meter is flagged.

- **Ask the data (copilot):** a tool-calling agent over eight read-only data tools (overview, zones, queue, meter detail, transformer balance, detection quality, alerts). Every number in an answer comes from a tool call, and each step is shown under the answer.
- **Inspection brief:** for any meter, the likely cause (hook bypass, gradual tampering, meter stopped, genuine drop, inconclusive), the evidence, what to check on site and a safety note. The cause must be one of the fixed set or the rule-based brief is used.
- **Smart alerts and digest:** rules over day-to-day changes (new flag, risk going up, a transformer suddenly losing more energy, a meter recovering), de-duplicated, then summarised into a morning digest.
- **Fallbacks:** Groq (`llama-3.3-70b-versatile`) is tried first, then NVIDIA NIM (`meta/llama-3.1-70b-instruct`). If no key is set or both fail, a rule-based answer is returned and labelled as such, so the app works with no key at all.
- **Observability:** every model call and every AI request is logged to SQLite (latency, tokens, tool calls, failovers, fallback reason) and shown on the AI operations page. AI endpoints are rate-limited per visitor when a key is configured.

AI evals (`python evals/ai_eval.py --mode rules|agent`) run on three unseen networks: brief causes are checked against the simulator's ground truth and copilot answers against values computed from the same data, with a check for invented meter ids. The rule-based baseline gets the cause right for 73% of meters and the theft-vs-not call right for 85%; the copilot baseline answers 80% of the 30 questions with no invented meters. The agent run needs a model key.

## The app

| Page | What it shows |
|---|---|
| Landing | The problem, a live single-line diagram of the worst transformer, measured accuracy |
| Overview | Loss estimate, flagged meters, today's digest, top of the queue, unmetered energy per transformer |
| Inspection queue | Filter by risk, zone and outcome; record "theft found" / "nothing found" inline |
| Meter detail | Daily usage vs neighbours and baseline, evidence from each layer, inspection brief, outcome form, transformer balance |
| Zones & transformers | Map, zones ranked by loss, a diagram per transformer, 24-hour feeder demand forecast |
| Alerts | Alerts by day and kind, with the digest |
| Ask the data | The copilot, with suggested questions and the steps behind each answer |
| Accuracy & ROI | Held-out and demo metrics, threshold sweep, AI eval results, an illustrative ROI with its assumptions listed |
| AI operations | Requests, fallback rate, latency and every model call |

## Run it

**Quick demo (no database):**

```bash
cd backend
pip install -e .
DEMO_SEED=1 DB_NAME=x DB_USER=x DB_PASSWORD=x uvicorn app.main:app --port 8000
# in another terminal
cd frontend && npm install
VITE_API_BASE=http://localhost:8000 npm run dev
```

`DEMO_SEED=1` generates the 60-day demo network in memory on startup. Add `GROQ_API_KEY` and/or `NVIDIA_NIM_API_KEY` to the backend environment to turn on the model-backed AI paths.

**Full stack (TimescaleDB for ingestion and forecasts):**

```bash
cp infra/.env.sample infra/.env
docker compose up --build
```

Dashboard on http://localhost:5173, API docs on http://localhost:8000/docs.

**Tests and evals:**

```bash
cd backend && pytest                      # detection, store/API and AI tests
python evals/detection_eval.py            # held-out detection metrics
python evals/ai_eval.py --mode rules      # AI baseline; --mode agent needs a key
```

| Environment variable | Purpose |
|---|---|
| `DEMO_SEED` | `1` loads the synthetic demo network on startup |
| `CORS_ORIGINS` | Comma-separated frontend origins |
| `GROQ_API_KEY`, `GROQ_MODEL` | Primary model for the AI features |
| `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_MODEL` | Fallback model |
| `OBS_DB_PATH` | Where the AI call log is written |
| `VITE_API_BASE` | Backend URL, set when building the frontend |

## Stack

FastAPI, Pydantic, pandas, NumPy and scikit-learn on the backend; React, TypeScript, Vite, TanStack Query, Recharts and Leaflet on the frontend; PostgreSQL with TimescaleDB in the Docker setup; GitHub Actions running the tests, the detection eval (with a recall gate) and the AI eval.

## Repository

```
backend/app/detection   scoring layers, confidence, tiers, queue ranking
backend/app/ai          LLM client, data tools, copilot and brief agents, alerts, call log
backend/app/api         REST endpoints (/api/v1 and /api/v1/ai)
backend/tests           unit and API tests
simulator/              synthetic network, thefts and decoys
evals/                  detection and AI evals, results in evals/results
frontend/               React app
infra/, db/             Docker and database setup
```

## Limits

- All data is simulated: real meter data has more noise, missing reads, tariff slabs and seasonal effects than this simulator.
- Rupee figures and the ROI page rest on stated assumptions, not billing data.
- Inspection outcomes are recorded and shown, but they don't retrain the thresholds yet.

Synthetic data only. No real consumer information is committed to this repository.
