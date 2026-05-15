# Architecture

How VidyutDrishti is put together, and where each decision is made. This page is the picture; the reasoning behind it is in [HLD.md](HLD.md), the per-module detail is in [LLD.md](LLD.md) and the measured behaviour is in [results.md](results.md).

Everything described here runs on **simulated data**. There is no connection to a real meter-data, billing or SCADA system.

## 1. Components

One FastAPI process holds the data, the detector, the queue, the forecast and the AI features. A React dashboard reads it over REST. There is no database in the running system: readings live in an in-memory store, the AI call log lives in a small SQLite file, and the published evaluation results are JSON files read from disk.

```mermaid
flowchart LR
    subgraph Data["Data (simulated)"]
        SIM["simulator/<br/>15-min meter and transformer readings<br/>injected thefts and vacant-house decoys"]
        SEED["demo_seed.py<br/>60 days, 8 transformers, 48 meters"]
    end

    subgraph Backend["FastAPI backend (backend/app)"]
        STORE[("store.py<br/>in-memory readings, topology,<br/>feedback, ground truth,<br/>cache per data version")]
        SCORE["detection/scoring.py<br/>L0 balance, L1 history,<br/>L2 neighbours, L3 outliers"]
        QUEUE["Queue, zones, overview<br/>(views on the store)"]
        FC["forecast/engine.py<br/>4-week seasonal mean + band"]
        LIVE["evaluation/live.py<br/>metrics vs ground truth"]
        subgraph AI["AI layer (app/ai)"]
            TOOLS["tools.py<br/>8 read-only data tools"]
            AGENTS["agents.py<br/>copilot, inspection brief"]
            ALERTS["alerts.py<br/>rules + model-written digest"]
            LLM["llm.py<br/>provider client"]
            OBS[("observability.py<br/>SQLite call log")]
        end
        ROUTES["api/routes.py and api/ai.py<br/>REST under /api/v1"]
    end

    PROV{{"Groq gpt-oss-120b<br/>then NVIDIA NIM gpt-oss-20b<br/>then rules"}}
    MCP["mcp_server.py<br/>same 8 tools over MCP (stdio)"]
    UI["React dashboard<br/>(frontend/src)"]
    RES[("evals/results/*.json")]

    SIM --> SEED --> STORE
    STORE --> SCORE --> QUEUE
    STORE --> FC
    SCORE --> LIVE
    STORE --> LIVE
    AGENTS --> TOOLS --> STORE
    ALERTS --> STORE
    AGENTS --> LLM
    ALERTS --> LLM
    LLM <--> PROV
    LLM --> OBS
    MCP --> TOOLS
    QUEUE --> ROUTES
    FC --> ROUTES
    AGENTS --> ROUTES
    ALERTS --> ROUTES
    OBS --> ROUTES
    RES --> ROUTES
    ROUTES <--> UI
```

Two rules shape the diagram:

- **The detector never calls a model.** Nothing in `detection/` imports anything from `ai/`. The AI layer reads detector output through `tools.py`, which reads only from the store.
- **Every number an AI feature states comes from a tool call.** The tools are read-only; the agents have no way to change a score, a queue position or a feedback record.

## 2. Data flow

### Startup and ingestion

With `DEMO_SEED=1` the API starts a background thread that builds the simulated network, loads it into the store, warms the queue cache and then computes how many days each theft took to be flagged. `/health` answers immediately; data endpoints answer 503 "still loading" until the readings are in. Readings can also be pushed in through `POST /api/v1/ingest/batch` and `/ingest/dt-batch`.

```mermaid
sequenceDiagram
    participant U as uvicorn startup
    participant S as demo_seed (thread)
    participant SIM as simulator
    participant ST as Store
    U->>S: start thread if DEMO_SEED=1
    U-->>U: /health answers at once
    S->>SIM: build_dataset(60 days, 8 DTs x 6 meters)
    SIM-->>S: meter readings, DT input, ground truth
    S->>ST: add_meter_frame, add_dt_frame, set_truth
    S->>ST: queue() warms the cache
    S->>ST: ready = True
    S->>ST: compute_detection_lag()
```

### A request

The store keeps one cache keyed by a data version number. Any new reading bumps the version and clears the cache, so scores are always for the data that is loaded and never stale.

```mermaid
sequenceDiagram
    participant UI as Dashboard
    participant API as /api/v1/queue/daily
    participant ST as Store
    participant SC as score_meters
    UI->>API: GET queue (limit)
    API->>ST: queue(target_date)
    ST->>ST: daily() from 15-min slots, scaled for missing slots
    ST->>SC: score_meters(daily, topology, date, dt_daily)
    SC-->>ST: one MeterScore per meter, 4 layers each
    ST->>ST: rank_queue: flagged meters by expected rupees
    ST-->>API: items with status from feedback
    API-->>UI: JSON
    UI->>API: POST /feedback (theft found / nothing found)
    API->>ST: record_feedback
    Note over ST: status is read from the latest feedback per meter
```

## 3. Detection layers (L0 to L3)

A meter is scored every day against its own recent window. Four independent checks produce a strength between 0 and 1 and a one-sentence explanation. They are combined into a confidence in `score_meters`; the confidence decides the tier and whether the meter is flagged. Formulas are in [LLD.md](LLD.md#3-detection-layers-l0-to-l3).

```mermaid
flowchart TD
    D["Daily kWh per meter<br/>(missing slots scaled up)"] --> L1
    D --> L2
    D --> L0
    DT["Daily kWh into each transformer"] --> L0

    L0["L0 Transformer balance<br/>unmetered share of input, last 7 days vs first 14<br/>noise floor 3 sigma<br/>subset search: which drops explain the gap"]
    L1["L1 Own history<br/>7-day mean vs 14-day baseline: ratio, z-score,<br/>zero-usage share, 3-week trend test"]
    L2["L2 Neighbours<br/>drop relative to median of the other meters<br/>on the same transformer"]
    L1 --> F
    L2 --> F
    L1 --> L3
    L2 --> L3
    L3["L3 Isolation forest<br/>ratio, relative drop, zero days, slope, z"]
    L3 --> F
    L0 --> F

    F{"Is the balance readable?"}
    F -- "yes" --> CA["conf = evidence x (0.25 + 0.55 x explained)<br/>+ 0.1 x L2 + 0.1 x L3 x explained"]
    F -- "no (no DT data or drop below noise)" --> CB["conf = evidence x 0.5<br/>+ 0.15 x L2 + 0.10 x L3<br/>(cannot exceed 0.75)"]
    CA --> T["Tier: HIGH 0.80, MEDIUM 0.65, REVIEW 0.50<br/>flagged at 0.50"]
    CB --> T
    T --> R["Rank by drop x 30 days x tariff x confidence"]
```

What this buys:

- A drop at one meter is not enough. Unless the transformer balance confirms that the missing energy is still being drawn, the confidence tops out at 0.75 (MEDIUM). This is what separates a theft from a vacant house.
- L3 can only add at most 0.10 to a score, so the outlier model can never flag a meter on its own.
- "Inconclusive" is a first-class answer. When a meter's drop is smaller than the transformer's noise floor, L0 reports that it cannot tell, instead of reporting "fine".

## 4. AI layer and failover

Models are used for language work only: writing an inspection brief from the detector's evidence, answering questions about the network, and summarising alerts. They do not decide whether a meter is flagged.

```mermaid
flowchart TD
    REQ["Copilot question, inspection brief<br/>or alert digest"] --> HAS{"Any provider key set<br/>and use_llm true?"}
    HAS -- "no" --> RULES
    HAS -- "yes" --> G["Groq<br/>openai/gpt-oss-120b"]
    G -- "error, timeout (25 s) or bad body" --> N["NVIDIA NIM<br/>openai/gpt-oss-20b"]
    G -- "answer" --> CHK
    N -- "answer" --> CHK
    N -- "error" --> RULES
    CHK{"Brief: cause in the<br/>5 allowed causes?<br/>Agent finished in 6 turns?"}
    CHK -- "yes" --> OUT["Response with mode = agent,<br/>provider, model, steps"]
    CHK -- "no" --> RULES["Deterministic answer from the same tools<br/>mode = rules, fallback_reason set"]
    RULES --> OUT
    G -.-> LOG
    N -.-> LOG
    OUT -.-> LOG[("SQLite log: every attempt,<br/>latency, tokens, tool calls, fallback reason")]
```

Behaviour worth knowing:

- Failover is per call: `llm.chat` tries Groq, records an error row if it fails, then tries NIM. If both fail it returns nothing and the caller uses its rules path.
- With no key at all the app still works. The response says `mode: rules` and why (`no_llm_provider`).
- The inspection brief must pick one of five fixed causes (`hook_bypass`, `gradual_tampering`, `meter_stopped`, `genuine_drop`, `inconclusive`). An answer outside the set is discarded and the rules brief is used. The fixed set is what lets the brief be scored against ground truth.
- AI endpoints are limited to 20 model-backed requests per 10 minutes per visitor when a key is configured. Briefs are cached per meter and data version.
- Model ids are read from `GROQ_MODEL` and `NVIDIA_NIM_MODEL`. The defaults were changed to gpt-oss when the earlier Llama ids were retired (see [errorlog.md](errorlog.md)).

## 5. MCP server

The copilot's eight read-only tools are also served over the Model Context Protocol so an external client (an IDE, a desktop assistant, another agent) can query the network without the dashboard. `mcp_server.py` registers each entry in `tools.TOOLS` with the same description the copilot sees. It adds no logic and exposes nothing that writes.

```mermaid
flowchart LR
    CLIENT["MCP client"] <-- "stdio" --> SRV["mcp_server.py<br/>FastMCP server 'vidyutdrishti'"]
    SRV --> REG["tools.TOOLS<br/>get_overview, list_zones, get_queue,<br/>find_meters, get_meter, get_dt_balance,<br/>detection_quality, get_alerts"]
    REG --> ST[("Store<br/>seeded synchronously at start")]
    COP["In-app copilot"] --> REG
```

The server seeds the demo network synchronously before it starts serving, so a client never sees an empty network.

## 6. Deployment on Render

`render.yaml` is a Render blueprint with two services. Both use `autoDeployTrigger: checksPass`, so a push to `main` deploys only after the GitHub checks pass. Secrets are declared with `sync: false` and entered in the Render dashboard.

```mermaid
flowchart LR
    DEV["git push to main"] --> GH["GitHub Actions<br/>tests, eval gates, lint,<br/>CodeQL, frontend build"]
    GH -- "checks pass" --> R1
    GH -- "checks pass" --> R2
    subgraph Render
        R1["vidyutdrishti-api<br/>Python web service, starter plan<br/>pip install ./backend<br/>uvicorn app.main:app<br/>DEMO_SEED=1, health check /docs"]
        R2["vidyutdrishti<br/>static site (npm ci, npm run build)<br/>VITE_API_BASE points at the API<br/>/* rewritten to /index.html"]
    end
    USER["Browser"] --> R2
    R2 -- "REST /api/v1" --> R1
    R1 -. "model calls" .-> EXT["Groq, NVIDIA NIM"]
```

Notes:

- The API holds all data in memory and re-seeds on every start, so a restart returns the same synthetic network rather than losing state. Feedback recorded through the UI is lost on restart.
- The backend image (`infra/Dockerfile.backend`) copies `evals/results` in, because `/metrics/evaluation` and `/ai/evals` read those JSON files.
- Locally, `docker-compose.yml` also starts TimescaleDB. It is used only by the original ingestion prototype; the API does not connect to it.
- The service runs on a small instance. That is why the pretrained forecaster (PyTorch) is opt-in and the shipped forecast is a simple seasonal mean.

## 7. Continuous checks

```mermaid
flowchart LR
    P["push or pull request"] --> T["Tests<br/>detection, store and API,<br/>AI with a fake LLM, MCP, end-to-end"]
    P --> E["Eval gates<br/>held-out detection, recall at least 0.85<br/>AI eval, rules baseline"]
    P --> Q["Quality<br/>ruff, vulture, radon and xenon, jscpd"]
    P --> S["Security<br/>CodeQL, OpenSSF Scorecard, Dependabot"]
    P --> F["Frontend typecheck and build"]
```

`scripts/validate.sh` runs the same set locally and prints a pass or fail line per stage.

## What is and is not wired

| Area | State |
|---|---|
| `detection/scoring.py`, `store.py`, `forecast/engine.py`, `evaluation/live.py`, `ai/*`, `api/*`, `mcp_server.py`, `demo_seed.py` | Live: this is what the API runs |
| `ingestion/`, `db/`, `features/`, `forecasting/` (Prophet), `risk/`, `feedback/`, `inspection/`, `audit/`, `detection/layer0..3_*.py`, `detection/confidence.py`, `detection/classifier.py`, `evaluation/{harness,leakage,backtest,baselines,metrics}.py` | Prototype from the first build, with prototype-grade tests under `logs/`. Not used by the API (the `detection/` and `evaluation/` package `__init__` files still import some of them, so they load but never run) |
| TimescaleDB schema in `db/migrations` | Prototype, used only by the ingestion CLI |
