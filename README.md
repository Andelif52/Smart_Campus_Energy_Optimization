Smart Campus Energy Optimization API

A REST API that produces a cost-optimized 24-hour energy schedule for a campus with solar generation and a battery. Operators can describe constraints in plain language (for example, "Do not charge the battery from 2 PM to 4 PM"), and the system turns those notes into rules the optimizer enforces.

Live deployment: https://smart-campus-energy-optimization.onrender.com
Interactive docs (Swagger): https://smart-campus-energy-optimization.onrender.com/docs

 Table of Contents

- [How It Works](#how-it-works)
- [Features](#features)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [Supported Operator Directives](#supported-operator-directives)
- [Optimization Model](#optimization-model)
- [LLM Integration and Validation](#llm-integration-and-validation)
- [Testing](#testing)
- [Docker](#docker)
- [Deployment](#deployment)
- [Project Structure](#project-structure)
- [Limitations](#limitations)

 How It Works

The API accepts a campus energy scenario: hourly demand, hourly solar forecast, electricity tariffs, battery configuration, and optional operator notes.

```
Energy Scenario
      |
      v
LLM Operator Note Interpreter
      |
      v
Directive Validation / Guardrails
      |
      v
Energy Optimization Solver
      |
      v
Final Schedule Validation
      |
      v
Optimization API Response
```

The LLM is used **only** to understand operator notes. All scheduling decisions are made by a deterministic optimization solver, so results are repeatable and every LLM output is checked before it reaches the optimizer.



## Features

- 24-hour campus energy optimization
- Natural language operator note interpretation (Gemini API)
- Structured directive extraction
- Deterministic guardrail validation
- Battery and solar handling
- Grid cost minimization
- REST API with interactive docs
- Docker support and cloud deployment on Render

---

## Quick Start

**Requirements:** Python 3.11+

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Create a `.env` file in the project root:

   ```env
   GEMINI_API_KEY=your_gemini_api_key
   GEMINI_MODEL=gemini-2.5-flash
   ```

   Never commit your API key. In deployment, set these as environment variables in your hosting platform instead.

3. Start the server:

   ```bash
   uvicorn app.main:app --reload
   ```

4. Open http://localhost:8000/docs for the Swagger UI.

**Dependencies:** fastapi, uvicorn, pydantic, python-dotenv, requests, numpy, scipy, pytest

---

## API Reference

### `GET /health`

Checks that the service is running.

```bash
curl http://localhost:8000/health
```

```json
{ "status": "ok" }
```

### `POST /optimize-energy`

Generates an optimized 24-hour schedule.

**Request fields**

| Field | Description |
|---|---|
| `scenario_id` | Identifier for the scenario |
| `operator_notes` | List of plain-language notes (optional) |
| `battery` | Battery configuration (see below) |
| `hours` | Exactly 24 entries, hour 0 through hour 23 |

**Battery configuration**

| Field | Description |
|---|---|
| `capacity_kwh` | Total battery capacity |
| `initial_energy_kwh` | Energy stored at the start of the day |
| `minimum_energy_kwh` | Lowest allowed stored energy |
| `max_charge_kwh_per_hour` | Maximum charge per hour |
| `max_discharge_kwh_per_hour` | Maximum discharge per hour |

**Hourly entry**

```json
{
  "hour": 0,
  "demand_kwh": 50,
  "solar_kwh": 0,
  "tariff_bdt_per_kwh": 8
}
```

**Example request** (the `hours` array is shortened here; send all 24 entries)

```json
{
  "scenario_id": "campus_demo_001",
  "operator_notes": [
    "Do not charge the battery from 2 PM to 4 PM.",
    "Solar generation is reduced by 50% from 12 PM to 2 PM."
  ],
  "battery": {
    "capacity_kwh": 200,
    "initial_energy_kwh": 100,
    "minimum_energy_kwh": 20,
    "max_charge_kwh_per_hour": 50,
    "max_discharge_kwh_per_hour": 50
  },
  "hours": [
    { "hour": 0, "demand_kwh": 50, "solar_kwh": 0, "tariff_bdt_per_kwh": 8 }
  ]
}
```

**Response fields**

| Field | Description |
|---|---|
| `scenario_id` | Echoes the request |
| `directive_interpretation` | How each operator note was interpreted |
| `hourly_plan` | Optimized 24-hour schedule |
| `total_grid_kwh` | Total grid energy used |
| `total_cost_bdt` | Total energy cost |
| `peak_grid_kwh` | Highest hourly grid usage |
| `plan_summary` | Short summary of the plan |

**Example response** (abbreviated)

```json
{
  "scenario_id": "campus_demo_001",
  "directive_interpretation": [],
  "hourly_plan": [],
  "total_grid_kwh": 500,
  "total_cost_bdt": 4000,
  "peak_grid_kwh": 80,
  "plan_summary": "Optimized energy schedule generated."
}
```

---

## Supported Operator Directives

Operator notes are converted into one of the directive types below.

### 1. Solar Reduction
Reduces available solar generation during specified hours.

> "Solar generation will be reduced to 50% from 12 PM to 2 PM."

```json
{
  "directive_type": "solar_reduction",
  "structured_adjustment": { "hours": [12, 13], "factor": 0.5 }
}
```

### 2. Minimum Battery Reserve
Keeps stored battery energy above a required level. Percentages are converted to kWh using battery capacity.

> "Keep at least 100 kWh in the battery from 6 PM to 9 PM."
> "Keep the battery at least 50% full." (For a 200 kWh battery, this is a 100 kWh minimum.)

### 3. No Charge Window
Prevents battery charging during specified hours.

> "Do not charge the battery from 2 PM to 4 PM."

### 4. No Discharge Window
Prevents battery discharging during specified hours.

> "Do not discharge the battery during peak hours."

### 5. Maximum Grid Import Window
Limits grid usage during specified hours.

> "Grid usage must stay below 50 kWh between 6 PM and 8 PM."

### 6. No Operation
Notes unrelated to energy scheduling are ignored.

> "The cafeteria will close tomorrow."

```json
{
  "directive_type": "no_op",
  "applies": false,
  "structured_adjustment": null
}
```

---

## Optimization Model

The optimizer minimizes total cost:

```
Total Cost = Σ (Grid Energy Used × Electricity Tariff)
```

subject to:

- Energy balance in every hour
- Battery capacity limits
- Minimum battery reserve
- Maximum charge and discharge rates
- Solar availability
- Operator directives
- End-of-day battery neutrality (the battery returns to its initial energy level after 24 hours)

---

## LLM Integration and Validation

The LLM handles natural language understanding: classifying each note, extracting time windows, and extracting parameters.

Its output is validated before entering the optimizer:

- Directive type must be one of the allowed types
- Time ranges must be valid
- Numeric values must be within limits
- Structured adjustments must have the correct format
- Invalid outputs are safely converted to `no_op`

---

## Testing

```bash
python -m pytest -v
```

The suite (28 tests, all passing) covers LLM interpretation conversion, guardrail validation, retry handling, no-op behavior, optimization constraints, battery behavior, and directive combinations.

---

## Docker

**Build and run locally**

```bash
docker build -t smart-energy-api .
docker run -p 8000:8000 --env-file .env smart-energy-api
```

**Use the published image**

```bash
docker pull andelif/smart-energy-api:v1
docker run -p 8000:8000 --env-file .env andelif/smart-energy-api:v1
```

The app listens on `0.0.0.0:8000` inside the container.

---

## Deployment

The service is deployed as a Docker web service on Render and exposes:

- A public HTTP URL
- `/health` and `/optimize-energy` endpoints

Set `GEMINI_API_KEY` and `GEMINI_MODEL` as environment variables in the hosting platform. No API keys are stored in source code.

---

## Project Structure

```
smart-energy-api/
├── app/
│   ├── main.py            # FastAPI app and endpoints
│   ├── schemas.py         # Request/response models
│   ├── integration.py     # Pipeline orchestration
│   ├── validator.py       # Directive guardrails
│   └── services/
│       ├── llm_service.py # Gemini operator note interpreter
│       └── optimizer.py   # Optimization solver
├── tests/
├── Dockerfile
├── requirements.txt
├── README.md
└── render.yaml
```

---

## Limitations

- Depends on the availability of the configured LLM provider
- Operator notes must match one of the supported directive categories
- Does not connect to live campus hardware
