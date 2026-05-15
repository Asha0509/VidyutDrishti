# VidyutDrishti — Feature Implementation Order

This file lists every prototype feature in the **exact order** it will be implemented. For each feature you will find:

- **Internal implementation details** — what gets built, where it lives in the repo, and the key rules/contracts.
- **Tech stack used** — runtime libraries, frameworks, and services the feature relies on.
- **Tools & methodologies applied** — design patterns, testing approach, and operational practices.

Each feature also maps to a folder under `logs/NN-feature-name/` that captures its tests, test review, changes log, and errors log.

Feature numbering is authoritative. Features are grouped by phase only for readability; implementation sequence is strictly top-to-bottom.

---

## Phase 1 — Foundation

### 01. Project Scaffolding & Docker Compose Skeleton

**Internal implementation details**
- Monorepo layout: `backend/`, `frontend/`, `simulator/`, `db/`, `infra/`, `logs/`.
- `docker-compose.yml` with placeholder services for `timescaledb`, `backend`, `scheduler`, `frontend`, `simulator-seeder` (final wiring in Feature 22).
- `infra/.env.sample` with DB credentials, ports, and feature flags.
- `backend/pyproject.toml` pinning Python 3.11 and base dependencies (`fastapi`, `uvicorn`, `pandas`, `numpy`, `sqlalchemy`, `alembic`, `apscheduler`, `prophet`, `scikit-learn`, `holidays`, `pydantic-settings`, `pytest`).
- `frontend/package.json` scaffolded via Vite (`react-ts`), with `recharts`, `leaflet`, `react-leaflet`, `axios`, `vitest`.
- Root `Makefile` with `make seed`, `make reset`, `make lint`, `make test`.

**Tech stack**
- Docker, Docker Compose
- Python 3.11, Poetry/uv (chosen at commit time)
- Node 20, pnpm, Vite, TypeScript
- GNU Make (cross-platform targets using shell)

**Tools & methodologies**
- Monorepo with per-package toolchains
- 12-factor config via environment variables
- Pre-commit hooks (ruff, black, mypy, eslint, prettier)
- Conventional Commits for history readability

---

### 02. Synthetic Data Simulator

**Internal implementation details**
- CLI: `python -m simulator.generate --config simulator/config.yaml --out data/`.
- Generates 2 DTs, 60 meters, 180 days, 15-minute cadence (~1.04M rows).
- Consumer mix: 70% domestic, 25% commercial, 5% small industrial.
- Load model: base diurnal profile per category × AC seasonal uplift (Mar–Jun) × monsoon dampener (Jun–Sep) × weekly pattern × holiday dip × Gaussian noise.
- Voltage model: 230V ± 5%; power factor 0.85–0.98 with category-specific noise.
- DT-level `kwh_in` = Σ meters + technical loss band (2–6%).
- Missing-reading injector: 0.5% gaps <1h, 0.2% gaps 1–6h, 0.05% gaps >6h.
- Three injected theft scenarios + two decoys (vacancy, equipment fault), logged to `injected_events.csv` as ground truth.
- Deterministic seed in config for reproducibility.

**Tech stack**
- Python 3.11, NumPy, Pandas, PyYAML, `holidays`

**Tools & methodologies**
- Parameterised YAML config (all knobs exposed; no magic numbers in code)
- Property-based sanity checks (row counts, value ranges, monotonic timestamps)
- Ground-truth separation: injected events are written to a distinct file and never consumed by detection code paths

---

### 03. TimescaleDB Schema & Migrations

**Internal implementation details**
- Alembic migration chain under `db/migrations/`.
- Hypertables: `meter_reading (meter_id, ts, kwh, voltage, power_factor, source, imputed)`, `dt_reading (dt_id, ts, kwh_in)`.
- Dimensions: `consumer`, `dt`, `feeder`, `tariff_slab`, `holiday`.
- Analytics: `forecast`, `zone_risk`, `feature_daily`, `flag`, `confidence`, `inspection`, `audit_log`, `ingest_errors`, `injected_events`, `job_run`.
- Continuous aggregates: `meter_hourly`, `meter_daily`, `dt_hourly`.
- Compression policy (>30 days) and retention policy (>365 days) declared but lenient for prototype.

**Tech stack**
- PostgreSQL 15, TimescaleDB 2.x
- SQLAlchemy 2.x, Alembic

**Tools & methodologies**
- Idempotent migrations with explicit `IF NOT EXISTS` guards
- Read-only DB role for the backend API, separate from the scheduler role
- Seeding script for dimension tables (`holidays`, `tariff_slab`) from YAML

---

### 04. Ingestion Pipeline + Data Quality Handling

**Internal implementation details**
- APScheduler job `ingest_readings` runs every 15 minutes; reads simulator output and upserts into hypertables using `ON CONFLICT DO NOTHING` on `(meter_id, ts)` / `(dt_id, ts)`.
- Validation: non-negative kWh, voltage in [200, 250], PF in [0, 1]; violations go to `ingest_errors`.
- Data-quality rules:
  - Gap <1h: forward-fill, mark `imputed=true`.
  - Gap 1–6h: linear interpolation, `imputed=true`, excluded from scoring downstream.
  - Gap >6h: scoring suspended for that meter-day.
  - Missing readings + voltage present elsewhere on DT ⇒ `Meter Stop` candidate event.
- Watermark table `job_run` records last processed timestamp per source.

**Tech stack**
- Python, Pandas, SQLAlchemy, APScheduler

**Tools & methodologies**
- Idempotent upserts
- Bulk `COPY` for large loads, row-level upsert for incrementals
- Structured JSON logs with job ID and row counts
- Retries with exponential backoff on transient DB errors

---

## Phase 2 — Forecasting

### 05. Prophet Forecasting Service

**Internal implementation details**
- `backend/app/forecasting/` module with `train_feeder_model(feeder_id)` and `predict(feeder_id, horizon_hours=24)`.
- One Prophet model per feeder (per DT in prototype), persisted as pickle under `models/prophet/{feeder_id}/{version}.pkl`.
- Regressors: `is_holiday_in`, `is_holiday_ka`, `is_summer`, `is_monsoon`, `lag_7_same_hour`, `lag_14_same_hour`.
- Output: 96 rows (15-min × 24h) with `yhat`, `yhat_lower` (P10), `yhat_upper` (P90), `model_version`, `generated_at`.
- Hourly APScheduler job refreshes forecasts for all feeders.
- Fallback to seasonal-naive when training rows < threshold.

**Tech stack**
- Facebook Prophet, Pandas, `holidays`, joblib

**Tools & methodologies**
- Model versioning via content hash + timestamp
- Offline training / online inference separation
- Graceful degradation path when Prophet training fails

---

### 06. Zone Risk Classification

**Internal implementation details**
- Rule-based classifier operating on the latest forecast:
  - `HIGH` if predicted peak ≥ 88% of feeder historical max.
  - `MEDIUM` if 75–88%.
  - `LOW` if < 75%.
- Historical max maintained per feeder and refreshed nightly.
- Results persisted to `zone_risk(feeder_id, ts, level, predicted_peak_kw, computed_at)`.

**Tech stack**
- Python, Pandas, SQLAlchemy

**Tools & methodologies**
- Declarative thresholds in config (`zone_risk.yaml`) so field tuning does not require code changes
- Hourly refresh tied to forecast job completion

---

### 07. Forecast Backtest + Baselines

**Internal implementation details**
- `backend/app/forecasting/backtest.py` provides a rolling-origin CV harness.
- Baselines implemented: historical-hour average, persistence (t−96), seasonal naive (t−672, i.e. same slot one week ago).
- Metrics: RMSE, MAPE, P10–P90 empirical coverage.
- Output: Markdown report `reports/forecast_backtest_<date>.md` plus JSON for dashboards.

**Tech stack**
- Python, Pandas, NumPy, scikit-learn metrics

**Tools & methodologies**
- Rolling-origin (walk-forward) evaluation
- Fixed holdout window (last 30 days) for final headline numbers
- Deterministic seed for any stochastic baseline

---

## Phase 3 — Detection

### 08. Daily Feature Engineering

**Internal implementation details**
- Nightly job computes per-meter, per-day features into `feature_daily`:
  - `mean_kwh`, `peak_mean_ratio`, `night_ratio` (22:00–05:00 kWh / total), `trend_slope` (7-day linear slope), `pf_avg`, `zero_read_rate`.
- Source is `meter_daily` + raw 15-min slice for night aggregation.
- Skips meter-days flagged as imputed >50% or gap-suspended.

**Tech stack**
- Python, Pandas, NumPy

**Tools & methodologies**
- Pure-function feature computations (no DB side effects)
- Vectorised Pandas operations; no row-wise Python loops

---

### 09. Layer 0 — DT Energy Balance

**Internal implementation details**
- Daily SQL-first job: for each DT-day compute `kwh_in − Σ meter kwh` and the percentage gap.
- Flag DT when gap > 8% sustained across ≥3 consecutive days.
- Rupee figure: `unaccounted_kwh × DT-weighted average tariff` (weighted by connected kVA by category).
- Writes to `flag (layer='L0', meter_id=NULL, dt_id, evidence_json)`.

**Tech stack**
- PostgreSQL, SQLAlchemy, Pandas

**Tools & methodologies**
- Set-based SQL for the balance computation, Python only for evidence assembly
- Idempotent per (dt_id, date)

---

### 10. Layer 1 — Z-Score Baseline

**Internal implementation details**
- 90-day rolling baseline per `(meter_id, hour, dow, month)`.
- Fires when `|Z| > 3` for ≥ 4 consecutive 15-minute slots.
- Runs every 15 minutes on the most recent window.
- Evidence JSON includes window start/end, Z-values, baseline mean/std.

**Tech stack**
- Python, Pandas, NumPy

**Tools & methodologies**
- Pre-aggregated baselines cached in memory per run
- Window-based detection with `consecutive_slots` constraint enforced via run-length encoding

---

### 11. Layer 2 — Peer Group Comparison

**Internal implementation details**
- Peer cohort = meters on the same DT with the same tariff category.
- Daily total compared to peer median; fires when value < `median − 2.5 × std` for 5 consecutive days.
- Evidence includes peer size, median, std, and daily deltas.

**Tech stack**
- Python, Pandas, NumPy, SQLAlchemy

**Tools & methodologies**
- Cohort recomputed daily to absorb new/removed meters
- Min-cohort threshold (e.g. 5) below which L2 abstains rather than producing low-signal flags

---

### 12. Layer 3 — Isolation Forest

**Internal implementation details**
- Scoring job: loads latest `feature_daily` rows and scores with the current model.
- Training job: monthly retrain using last 90 days of data; `contamination = 0.03`.
- Model artefact: `models/isoforest/{version}.pkl` + feature-schema sidecar.
- Writes per-meter-per-day anomaly score and a binary fire flag.

**Tech stack**
- scikit-learn `IsolationForest`, joblib, NumPy, Pandas

**Tools & methodologies**
- Feature schema pinned alongside the model to prevent silent drift
- Evaluation during retrain against the injected-events set (for prototype sanity)

---

### 13. Confidence Engine

**Internal implementation details**
- Daily rollup consumes `flag` rows and emits a single `confidence` record per meter:
  - `HIGH` = L0 fired AND ≥ 2 of {L1, L2, L3}.
  - `MEDIUM` = ≥ 2 of {L1, L2, L3}.
  - `REVIEW` = exactly 1 of {L1, L2, L3}.
  - `NORMAL` = none.
- `layers_fired[]` array recorded for UI.

**Tech stack**
- Python, SQLAlchemy

**Tools & methodologies**
- Pure deterministic rule set; no ML in the fusion step (for auditability)
- Unit tests enumerate all 16 combinations of (L0, L1, L2, L3)

---

### 14. Behavioural Classifier

**Internal implementation details**
- Deterministic decision tree over layer signatures + auxiliary signals (voltage presence, peer cohort status, abruptness).
- Classes: Hook Bypass, Meter Tampering, Meter Stop, Vacant/Legitimate, Equipment Fault.
- Produces a one-line human-readable evidence string consumed by the UI.

**Tech stack**
- Python

**Tools & methodologies**
- Rules authored in one module; no branching logic in the UI
- Table-driven classification; adding a new class requires only a config change and a test

---

### 15. Leakage Quantification

**Internal implementation details**
- `leakage_kwh_month = max(0, peer_median_monthly_kwh − actual_billed_kwh)`.
- `leakage_inr_month = leakage_kwh_month × tariff_rate(category, slab)`.
- Tariff rate resolved via join through `consumer.tariff_category` to `tariff_slab`.
- Result stored alongside the `confidence` record.

**Tech stack**
- Python, SQLAlchemy, Pandas

**Tools & methodologies**
- Tariff slabs sourced from a YAML file so illustrative values can be replaced without code changes
- Explicit unit tests for slab-boundary cases

---

### 16. Inspection Queue

**Internal implementation details**
- Materialised view / table combining `confidence`, `consumer`, `leakage`, latest evidence.
- Default filter: `confidence IN (HIGH, MEDIUM)`; sort `leakage_inr_month DESC`.
- Columns: meter ID, address, consumer type, leakage Rs./month, confidence, behaviour, one-line evidence.

**Tech stack**
- PostgreSQL materialised view or a derived table refreshed nightly

**Tools & methodologies**
- Denormalised read model for UI latency
- Concurrent refresh (`REFRESH MATERIALIZED VIEW CONCURRENTLY`) to avoid locking

---

## Phase 4 — UI & Ops

### 17. FastAPI Endpoints

**Internal implementation details**
- Endpoints (all read-only except `POST /feedback`):
  - `GET /health`, `GET /metrics`
  - `GET /forecast?feeder_id=&horizon=`
  - `GET /zone-risk?at=`
  - `GET /inspection-queue?min_confidence=&limit=`
  - `GET /meter/{id}` — profile, 30-day curve, peer median, flags, evidence
  - `GET /audit/{flag_id}`
  - `POST /feedback`
- Pydantic schemas in `backend/app/schemas/`.
- CORS configured for the frontend origin.

**Tech stack**
- FastAPI, Pydantic v2, Uvicorn, SQLAlchemy

**Tools & methodologies**
- Dependency-injected DB session per request
- OpenAPI schema auto-served at `/docs`
- Read-only DB role enforced at the connection string level

---

### 18. React Dashboard

**Internal implementation details**
- Views:
  - **Zone Risk Map** — Leaflet tiles, DT markers coloured by level, auto-refresh hourly.
  - **Forecast** — Recharts line + P10/P90 band + actuals overlay.
  - **Inspection Queue** — sortable/filterable table with confidence badges.
  - **Meter Detail** — 30-day load vs peer median, layer-fired badges, evidence, feedback form.
  - **Audit Drawer** — JSON viewer for flag evidence.
- KPI header: precision@HIGH, hook-bypass recall, FPR, mean detection lag, total Rs. at risk.

**Tech stack**
- React, TypeScript, Vite, Recharts, Leaflet, react-leaflet, axios, TanStack Query

**Tools & methodologies**
- Typed API client generated from OpenAPI
- Component-level tests with Vitest + Testing Library
- Responsive layout (CSS grid) with accessible colour ramps for risk levels

---

### 19. Feedback Loop + Recalibration

**Internal implementation details**
- `POST /feedback {meter_id, outcome, notes}` persists to `inspection`.
- Weekly recalibration job (active after day 90):
  - Computes precision@HIGH and FPR over the last 90 days.
  - Adjusts L1 Z-threshold within [2.5, 3.5] and L2 σ multiplier within [2.0, 3.0] to keep precision ≥ 70% and FPR ≤ 15%.
  - New thresholds written to `config_versioned` with effective-from timestamp.

**Tech stack**
- Python, SQLAlchemy, APScheduler

**Tools & methodologies**
- Grid search over a bounded parameter space; no gradient methods
- Every recalibration event recorded in `audit_log`

---

### 20. Audit Logging

**Internal implementation details**
- Every flag write appends to `audit_log (ts, actor='system', action='flag', payload_json)` including layer, inputs window, threshold, model version, evidence.
- Confidence labels and feedback events follow the same pattern.
- `GET /audit/{flag_id}` returns the raw payload for inspection.

**Tech stack**
- PostgreSQL (append-only table), SQLAlchemy

**Tools & methodologies**
- Append-only discipline; no updates or deletes
- Payload JSON validated against a Pydantic model before insertion

---

### 21. Evaluation Harness

**Internal implementation details**
- `backend/app/eval/` joins confidence + flag output against `injected_events`.
- Computes: forecast RMSE vs 3 baselines, P10–P90 coverage, precision@HIGH, hook-bypass recall, mean detection lag, FPR.
- Generates a Markdown report and a JSON artefact served to the dashboard KPI header.

**Tech stack**
- Python, Pandas, NumPy, scikit-learn

**Tools & methodologies**
- Single source of truth for ground-truth (the simulator)
- Report checked into `reports/` per run for historical comparison

---

### 22. Docker Compose + End-to-End Test

**Internal implementation details**
- Final `docker-compose.yml` wires: `timescaledb`, `backend-api`, `scheduler-worker`, `simulator-seeder` (one-shot), `frontend`.
- Volumes: `pgdata`, `models/`.
- Named Docker network; healthchecks for DB and API.
- E2E test (`tests/e2e/test_demo_runbook.py`):
  1. `docker compose up -d --build` on a fresh volume.
  2. Wait for seeder + first forecast + first detection pass.
  3. Assert all 3 injected theft scenarios appear with correct confidence and ranking.
  4. Assert evaluation metrics meet the documented targets.

**Tech stack**
- Docker, Docker Compose, pytest, requests

**Tools & methodologies**
- Fresh-clone reproducibility as the acceptance criterion
- Test runs in CI on every PR touching infra or any detection layer

---

## Out of Scope (prototype)

Explicitly excluded to keep scope honest:

- Real AMI / SCADA / MDM / billing integration or any write-back
- Real consumer PII
- LLM-based explanations or reasoning
- Mobile app, SMS/IVR dispatch, workforce management integrations
- Multi-tenant authentication (a mock inspector identity is sufficient)
- Kannada localisation (stretch goal only)
