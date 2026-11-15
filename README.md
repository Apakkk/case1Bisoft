# Carrier Selection API

Selects the best container carrier for an order and explains why. Hard constraints, price,
distance, ranking and the explanation are **deterministic code**. The TypeSafe **Jev** model is
used only where the *data* is free text: it matches the order's description against each carrier's
description (and fills order fields that were left empty).

- REST API: `POST /api/v1/quotes`, `/api/v1/carriers` and `GET /api/v1/cities` (Swagger at `/docs`)
- Admin screen: carrier CRUD with an editable free-text description, a quote form and a rules page;
  every city input suggests US cities as you type
- Rules in `config/rules.yaml`: putting price second is a click on `/admin/rules` (or a YAML edit), not code
- The 7 orders from the case are tests (unit, service, API and end-to-end against PostgreSQL)

## Quick start

Requirements: Docker, [uv](https://docs.astral.sh/uv/) and make.

```bash
cp .env.example .env          # add TYPESAFE_API_KEY (and optionally ORS_API_KEY)
make run                      # PostgreSQL + API in Docker; schema and seed load on first start
make case-orders              # sends the 7 case orders to the running API: 7/7
```

- Admin screen: http://localhost:8000/admin/carriers
- Quote form: http://localhost:8000/admin/quote
- Rules (ranking priority): http://localhost:8000/admin/rules
- API docs: http://localhost:8000/docs

Local development: `make install`, `make dev` (database in Docker, API with auto-reload),
`make check` (ruff + mypy --strict + fast tests).

## Architecture

Classic layered design: Controller → Service → Repository, with the selection rules in a pure
module that never touches the database, HTTP or Jev.

```mermaid
flowchart TB
  subgraph CV["Controllers and views"]
    QC["quote_controller<br/>POST /api/v1/quotes"]
    CC["carrier_api_controller<br/>/api/v1/carriers"]
    YC["city_api_controller<br/>GET /api/v1/cities"]
    AC["admin controllers<br/>Jinja2 + HTMX"]
  end
  subgraph SV["Services"]
    QS[QuoteService]
    CS[CarrierService]
    YS[CityService]
  end
  SEL["selection/ (pure)<br/>constraints · criteria · rank · explanation"]
  subgraph IF["Interfaces (fakes in tests)"]
    DP[DistanceProvider]
    JC[JevClient]
    CR[CarrierRepository]
    RS[RulesSource]
    YR[CityRepository]
  end
  QC --> QS
  CC --> CS
  YC --> YS
  AC --> QS & CS & YS
  QS --> SEL
  QS --> DP & JC & CR & RS
  CS --> JC & CR & RS
  YS --> YR & ORS
  DP --> YR
  DP --> ORS[(OpenRouteService)]
  JC --> JEV[(Jev API)]
  CR --> PG[(PostgreSQL)]
  YR --> PG
  RS --> YAML[(config/rules.yaml)]
```

```
app/
  controllers/   HTTP + admin routes (thin)          views/       Jinja2 templates, form view-models
  services/      Quote, Carrier, City services        selection/   pure rules: no I/O, mypy --strict
  repositories/  PostgreSQL (parametrized SQL), rules  clients/     Jev adapter, distance chain, ORS
  models/        domain dataclasses                   schemas/     Pydantic API DTOs
config/          rules.yaml, distances.yaml (case table), cities.csv, city_aliases.yaml
db/init/         schema + seed (run once on an empty volume); db/migrations/ for later changes
```

Two rules keep the services thin: selection rules live in `app/selection/` and receive plain data;
every external dependency is injected through an interface and wired in one place
(`app/dependencies.py`). That is why the selection tests need no database, network or Jev.

## How a quote is made

1. **Validate and normalize** the order: city aliases (`Ft. Lauderdale` → `Fort Lauderdale`),
   catalog values (`reefer` → `Reefer`).
2. **Fill missing fields** from the order's `description`: a regex first (`40 ft`, `40'lık`, `40HC`;
   a unit is required so "20 tons" is never 20 ft), then Jev, with confidence bands.
3. **Distance** from the chain below (never estimated by a model).
4. **Filter**: every carrier through every hard constraint; all failure reasons are kept.
5. **Price** each eligible carrier with `Decimal`, rounded half-up to cents.
6. **Ask Jev once** (only if there is free text to check): does the order description conflict with
   each eligible carrier's description, and does it ask for a specific carrier?
7. **Rank**: a carrier requested in the order description first (fixed, not a rule), then the others
   lexicographically by `rules.yaml`: total cost → HQ distance to the origin → name. A criterion only
   matters when all criteria above it are exactly equal.
8. **Compatibility**: a confident conflict removes the carrier ("S-Logistics ile çalışmak istemiyorum"
   removes S-Logistics). Without an order description, only carrier descriptions that may restrict
   orders are checked. Free text never adds a carrier that fails a hard constraint.
9. **Requested carrier**: "A-Logistics ile çalışmak istiyorum" puts A-Logistics first even if it is
   more expensive, but only if it passes every constraint; the rest follow in rule order. Otherwise
   the explanation says why it cannot carry the order, and the next eligible carrier is selected.
   This is automatic, not one of the configurable ranking rules.
10. **Status**: `selected`, `needs_review`, `needs_input` or `no_carrier`.
11. **Explanation** in Turkish (for the operations team), generated by template from the trace.

## Where Jev is used, and what stays deterministic

Jev is a decision model: it answers choice and yes/no questions with probabilities and does not
produce text or numbers. Every answer it gives is returned in `jev_calls`.

| Step | Question to Jev | When it is called |
|---|---|---|
| Order interpretation | Which catalog cargo type / container size does this text describe? (`Choice`) | Only when the field is missing and the regex did not find it |
| Compatibility | Do this order (with its description) and this carrier's description conflict? (`Noul`, one per carrier, batched) | Every eligible carrier when the order has a description; otherwise only carriers whose description may restrict |
| Requested carrier | Which carrier, if any, does the order description ask for? (`Choice` over every carrier name, in the same request) | When the order has a description |
| Carrier pre-check | Does this description restrict which orders the carrier accepts? (`Noul`) | Once, when a changed carrier description is saved |

| Stays in deterministic code | Why |
|---|---|
| Hard constraints (distance, size, cargo type) | The case states them exactly; they must be testable and explainable |
| Price | Arithmetic; `Decimal`, never a model or a float |
| Distance | Case table, cache, routing API or Haversine; a model would make numbers up |
| Ranking and tie-breaks | Priority order from the case, configurable on `/admin/rules` (`rules.yaml`) |
| What happens to a requested carrier | Jev only names it; whether it is eligible, and who is next, is decided by the rules |
| Explanation text | Built from the decision trace by template; Jev does not write text |
| Status | Derived from the rules and the confidence bands |

Cost: each Jev request has a fixed overhead (~290 input tokens measured) plus ~130 per carrier
compared (685 measured for three), so questions are batched: at most one request to interpret an
order and one for all candidates. Structured orders without a description, against carriers without
restrictive descriptions, make **no** Jev call (the seven case orders included).

## Low confidence

Thresholds live in `config/rules.yaml` (`confidence`). They are starting values, to be tuned on a
labeled sample for the pinned model version.

| Situation | Behaviour |
|---|---|
| Field confidence ≥ 0.85 | Used; marked `inferred: jev` |
| 0.60 ≤ confidence < 0.85 | Used, result computed, status `needs_review` with a warning |
| Confidence < 0.60 | Not guessed: no carrier is chosen, status `needs_input` naming the missing field |
| P(Hazardous) ≥ 0.15 while another type won | `needs_review` (asymmetric: missing a hazmat load is the costly error) |
| Compatibility: P(conflict) ≥ 0.85 | Carrier removed; the texts Jev compared are quoted as the reason |
| Compatibility: 0.15 < P(conflict) < 0.85 on the winner | Winner kept, status `needs_review` |
| Requested carrier: confidence ≥ 0.85 / 0.60–0.85 / < 0.60 | Used / used with `needs_review` / ignored with a warning (price order applies) |
| Jev unavailable (timeout, auth, quota) or not configured | Missing fields → `needs_input`; an order description or restrictive carrier descriptions → `needs_review`. The ranking is kept and nothing is silently skipped |
| Approximate distance within 10% of a carrier limit | `needs_review`: the real road distance could change eligibility |

## Distance

`DistanceProvider` tries, in order:

1. Same city → 0
2. The case's table (`config/distances.yaml`, symmetric)
3. PostgreSQL cache of earlier routing results (A–B and B–A share one row)
4. OpenRouteService driving distance (if `ORS_API_KEY` is set). Coordinates come from `cities.csv`,
   then the `cities` table (cities found by the suggestions below), and only then from ORS geocoding
5. Haversine × 1.2 using `config/cities.csv`; flagged `approximate: true`
6. Otherwise `422 UNKNOWN_LOCATION`

HQ → origin distances (for the tie-break) use the same chain and are only looked up when more than
one carrier is eligible. A carrier whose HQ cannot be located is ranked last with a warning.

## City suggestions

The HQ city, origin and destination inputs open a list of up to 5 cities while you type
(`app/static/city-autocomplete.js`, a server-rendered list from `GET /admin/cities/suggest`):

- Matching ignores case, dots and extra spaces (`orl`, `ORL`, `st. l`; a Turkish `İ` counts as `i`).
  Names that start with the letters come first, then names with a later word that does (`lau` →
  Fort **Lau**derdale). Letters in the middle of a word do not match, so `o` suggests Orlando, not Boston.
- Catalog cities (`cities.csv` + aliases, alphabetical) come before cities found online (in
  OpenRouteService's relevance order). The typed letters are bold; online ones carry an `ORS` tag.
- Local first: the catalog and the `cities` table. OpenRouteService autocomplete
  (`layers=locality`, US only: cities and towns, never districts, streets or venues) is asked only
  when local matches fill fewer than 5 rows and at least 3 letters are typed. What it returns is
  stored, so the same city comes from the database next time and needs no geocoding for a quote.
- Quota guards: 250 ms debounce with the older request aborted, each query sent once per process, a
  shorter query whose answer was complete covers longer ones, 3 s timeout, 60 s pause after a failure.
- Up/Down move, Enter picks (an open list never submits the form), Escape closes. Picking is optional:
  free text is validated exactly as before. If ORS is down or not configured, local cities are shown
  with a note.

## API

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/quotes` | Business outcomes (including "no carrier") are `200` with a `status` |
| GET, POST | `/api/v1/carriers` | `409 DUPLICATE_CARRIER` for a duplicate name (case-insensitive) |
| GET, PUT, DELETE | `/api/v1/carriers/{id}` | `404 CARRIER_NOT_FOUND` |
| GET | `/api/v1/cities?q=orl&limit=5` | City suggestions `{"items": [{"name", "state", "source"}], "warnings": []}`; `limit` 1–10 |
| GET | `/health` | Includes a database probe |

Errors are `{"error": CODE, "detail": ...}`: `UNKNOWN_LOCATION`, `INVALID_ORDER`,
`INVALID_CARRIER` (422), `INVALID_RULES` (500, e.g. a typo in `rules.yaml`). Unknown request fields
are rejected with 422, so a misspelled field is never silently ignored.

```bash
curl -s localhost:8000/api/v1/quotes -H 'content-type: application/json' \
  -d '{"origin": "Miami", "destination": "Atlanta", "container_size": 20, "cargo_type": "Reefer"}'

# Free text: the container size is parsed, the cargo type comes from Jev
curl -s localhost:8000/api/v1/quotes -H 'content-type: application/json' \
  -d '{"origin": "Miami", "destination": "Atlanta", "description": "20 ft container of frozen shrimp"}'

# A requirement in the description: Jev finds the conflict, M-Logistics ($235) is selected
curl -s localhost:8000/api/v1/quotes -H 'content-type: application/json' \
  -d '{"origin": "Miami", "destination": "Orlando", "container_size": 40, "cargo_type": "Dry",
       "description": "S-Logistics ile çalışmak istemiyorum"}'
```

```json
{
  "status": "selected",
  "carrier": "B-Logistics",
  "total_cost": "660.00",
  "currency": "USD",
  "distance": {"miles": "660", "source": "case_table", "approximate": false},
  "order": {"origin": "Miami", "destination": "Atlanta", "container_size": 20, "cargo_type": "Reefer", "inferred": {}},
  "ranking": [
    {"carrier": "B-Logistics", "total_cost": "660.00", "hq_distance_miles": "30"},
    {"carrier": "M-Logistics", "total_cost": "660.00", "hq_distance_miles": "1190"}
  ],
  "rejected": [
    {"carrier": "S-Logistics", "reasons": ["Mesafe 660 mil, üst sınır 300 mil", "20 ft konteyner taşımıyor (taşıdığı: 40, 45 ft)", "Reefer yük taşımıyor (taşıdığı: Dry)"]},
    {"carrier": "A-Logistics", "reasons": ["Mesafe 660 mil, üst sınır 200 mil", "20 ft konteyner taşımıyor (taşıdığı: 45 ft)", "Reefer yük taşımıyor (taşıdığı: Dry, Hazardous)"]}
  ],
  "jev_calls": [],
  "warnings": [],
  "explanation": "Rota Miami → Atlanta: 660 mil; 20 ft, Reefer. B-Logistics seçildi: toplam $660.00 (660 mil × $1.00/mil). Toplam ücret eşit; belirleyici kriter: merkezin çıkış noktasına uzaklığı — B-Logistics: 30 mil (Fort Lauderdale), M-Logistics: 1190 mil (Houston). Elenenler: ..."
}
```

Money and miles are decimals serialized as strings, so nothing is rounded through a float.

## Tests

| Layer | What it checks | DB | Network | Jev |
|---|---|---|---|---|
| `tests/unit/selection` | The 7 case orders, inclusive limits (200/250/300), tie-breaks, ranking swap via config, rules validation, explanations | – | – | – |
| `tests/unit/distance` | Normalization, case table, Haversine, chain order, city suggestion ranking, ORS client (httpx MockTransport) | – | – | – |
| `tests/unit/services` | Confidence bands, hazardous asymmetry, order/carrier compatibility, Jev outage, batching, city suggestion quota guards | – | – | fake |
| `tests/api` | REST endpoints and the admin screen over TestClient | fake | – | fake |
| `tests/integration` | PostgreSQL repositories, CHECK constraints, the real app wiring | ✓ | – | – |
| `tests/live` | Two tiny real Jev requests (opt-in, costs tokens) | – | ✓ | real |

```bash
make test        # 251 tests, no database/network/Jev, < 2 s
make test-db     # 29 tests against the PostgreSQL container (each test rolls back)
make test-live   # 2 real Jev requests
make case-orders # the 7 orders against the running API
```

| # | Route | Order | Result |
|---|---|---|---|
| 1 | Miami → Fort Lauderdale | 40 ft Reefer | M-Logistics, $30.00 |
| 2 | Miami → Orlando | 40 ft Dry | S-Logistics, $94.00 |
| 3 | Miami → Atlanta | 20 ft Reefer | B-Logistics, $660.00 (tie with M; HQ 30 mi vs 1190 mi) |
| 4 | Jacksonville → Savannah | 45 ft Hazardous | A-Logistics, $280.00 |
| 5 | Tampa → Jacksonville | 45 ft Dry | S-Logistics, $80.00 |
| 6 | Miami → Houston | 45 ft Reefer | No carrier, with every reason per carrier |
| 7 | Tampa → Orlando | 20 ft Hazardous | M-Logistics, $85.00 |

## Changing the rules

`config/rules.yaml` is re-read on the next request after it changes (the Docker container mounts
`config/`), so no restart is needed. A typo returns `500 INVALID_RULES` naming the problem.

**Change the ranking priority on screen.** `/admin/rules` lists the ranking criteria: move them up or
down, remove or add them, then save. Saving rewrites only the `ranking` block of `rules.yaml` (comments
and other sections are kept) after validating it. A criterion added in code appears there automatically.

**Add a carrier.** Use the admin screen or `POST /api/v1/carriers`. Its HQ city is normalized; a
description is pre-checked by Jev and shown as a badge.

**Put price second.** On `/admin/rules` move "Toplam ücret" below "Merkezin çıkış noktasına uzaklığı"
and save, or edit the file:

```yaml
ranking:
  - hq_proximity
  - total_cost
```

With the case's four carriers this changes none of the seven results (the cheapest carrier is
also the closest in every tie-free case). Adding a carrier based in the origin city shows the effect.

**Add a ranking criterion from existing data** (e.g. lowest rate per mile): one entry in
`app/selection/criteria.py`, then add it on `/admin/rules`. This is a code change: in Docker run
`make run` to rebuild (or use `make dev`, which reloads code automatically).

```python
# app/selection/criteria.py (fmt_rate comes from app.selection.formatting)
"lowest_rate": Criterion(
    key=lambda c: (c.carrier.rate_per_mile,),
    label="mil başı ücret",
    describe=lambda c: fmt_rate(c.carrier.rate_per_mile),
),
```

**Add a criterion that needs a new carrier attribute** (e.g. a rating, higher is better):

1. `db/migrations/002_add_rating.sql`:
   `ALTER TABLE carriers ADD COLUMN IF NOT EXISTS rating NUMERIC(2,1) NOT NULL DEFAULT 3.0;`
   then `make migrate` (keeps the data; never `make reset-db` during a demo).
2. Add `rating` to `Carrier`, the repository's column list, `CarrierIn`/`CarrierOut` and the form.
3. Criterion with a negated key: `key=lambda c: (-c.carrier.rating,)`.
4. Add `rating` to `ranking` in `rules.yaml`.

**Add a hard constraint**: a function returning a Turkish reason or `None`, registered in
`CONSTRAINTS` (`app/selection/constraints.py`), and its name under `filters`.

**Add a cargo type or container size**: one line in `catalog`. Orders and carriers accept it at once.

**Tune Jev thresholds**: the `confidence` section.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql://carrier:carrier@localhost:5433/carrier` | Host port 5433 avoids a local PostgreSQL on 5432 |
| `TYPESAFE_API_KEY` | – | Jev. Without it, free text asks for input and restrictive notes need review |
| `JEV_MODEL` | SDK default `jev-latest` | Pin a version once thresholds are tuned |
| `JEV_TIMEOUT_SECONDS` | `5` | Per request; one retry |
| `ORS_API_KEY` | – | OpenRouteService; without it off-table routes use Haversine and city suggestions stay local |
| `RULES_PATH` | `config/rules.yaml` | |

## Decisions

- **Python 3.12 + FastAPI**: the official Jev SDK is Python; Pydantic gives validation and Swagger
  from one model; `Decimal` is in the standard library.
- **Filter + lexicographic ranking** instead of a weighted score: the case gives rules in priority
  order, and a weighted score would let proximity outweigh a cheaper price.
- **PostgreSQL + parametrized SQL** (psycopg 3, no ORM): three small tables; `NUMERIC` money and
  `CHECK` constraints as a safety net behind service validation.
- **Server-rendered Jinja2 + HTMX**: no build step, one process, the same services as the API.
- **Jev never picks the carrier**: the rule is deterministic; a probabilistic choice could be neither
  tested nor explained.

## Assumptions and limitations

- "Closest to the departure point" is read as the carrier HQ's distance to the order origin.
- Distance limits are inclusive (`<=`, `>=`); an empty limit means unbounded.
- Confidence thresholds are starting values, not calibrated on a labeled set yet.
- Free text (order or carrier description) can only narrow eligibility; it never re-ranks. Missing
  information is not a conflict. Price-changing notes ("+20% over 500 miles") need a structured
  field, because Jev does not do arithmetic.
- Order and carrier descriptions are sent to the Jev API; they should not contain confidential data.
- City names are matched to the first entry in `cities.csv` (e.g. Portland is Portland, OR);
  geocoding is limited to the US. Cities are known by name only, so the `cities` table keeps one row
  per name (the first one found: Springfield, IL).
- ORS's locality layer includes census-designated places, so `boca` also suggests communities next to
  Boca Raton (Boca West, Boca Pointe). They are real places with coordinates and rank after the city.
- The distance cache never expires (road distances rarely change).
- The admin screen has no authentication.
