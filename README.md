# Carrier Selection API

Selects the best container carrier for an order and explains why. Hard constraints, price,
distance, ranking and the explanation are **deterministic code**. The TypeSafe **Jev** model is
used only where the *data* is free text: it matches the order's description against each carrier's
description (and fills order fields that were left empty).

- Home page: the carriers as a truck showroom, each name lettered on a trailer; a new carrier is a new truck
- REST API: `POST /api/v1/quotes`, `/api/v1/carriers` and `GET /api/v1/cities` (Swagger at `/docs`)
- Admin screen: carrier CRUD with an editable free-text description, a quote form and a rules page;
  every city input suggests US cities as you type, and a mistyped city is answered with "did you mean";
  a description that contradicts the chosen cargo type or size asks for confirmation before a carrier is chosen
- Distances: the case table always wins; other routes come from OpenRouteService once and are stored
- Rules in `config/rules.yaml`: putting price second is a click on `/admin/rules` (or a YAML edit), not code
- The 7 orders from the case are tests (unit, service, API and end-to-end against PostgreSQL)

## Quick start

Requirements: Docker, [uv](https://docs.astral.sh/uv/) and make. Python is 3.12 everywhere: `.python-version`
for uv locally, `python:3.12-slim` in the image. Jev is pinned to `jev-1.14.0`.

```bash
cp .env.example .env          # add TYPESAFE_API_KEY (and optionally ORS_API_KEY)
make run                      # PostgreSQL + API in Docker; schema and seed load on first start
make case-orders              # sends the 7 case orders to the running API: 7/7
```

- Home page (truck showroom): http://localhost:8000/
- Admin screen: http://localhost:8000/admin/carriers
- Quote form: http://localhost:8000/admin/quote
- Rules (ranking priority): http://localhost:8000/admin/rules
- API docs: http://localhost:8000/docs

Local development: `make install`, `make dev` (database in Docker, API with auto-reload; it stops
the Docker API container first, because both listen on port 8000),
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
config/          rules.yaml, distances.yaml (case table), cities.csv + city_aliases.yaml (case catalog),
                 us_cities.csv (5,105 US cities, built by scripts/build_us_cities.py)
db/init/         schema + seed (run once on an empty volume); db/migrations/ for later changes
```

Two rules keep the services thin: selection rules live in `app/selection/` and receive plain data;
every external dependency is injected through an interface and wired in one place
(`app/dependencies.py`). That is why the selection tests need no database, network or Jev.

## How a quote is made

1. **Validate and normalize** the order: city aliases (`Ft. Lauderdale` → `Fort Lauderdale`),
   catalog values (`reefer` → `Reefer`).
2. **Fill missing fields** from the order's `description`: a regex first (`40 ft`, `40'lık`, `40HC`, `2x40HC`;
   a unit is required so "20 tons" is never 20 ft, and a date like "ayın 20'sinde" is not a size), then Jev,
   with confidence bands. Jev may answer `not_stated`: the text does not say what the cargo is.
   **Check entered fields** against the description: a size stated in the text (regex) and the cargo type Jev
   reads in the text alone (it is never shown the entered value). An entered field is never overridden: a
   contradiction stops with `needs_confirmation` until the order is resent with `confirm_mismatch: true`.
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
10. **Status**: `selected`, `needs_review`, `needs_input`, `needs_confirmation` or `no_carrier`.
11. **Explanation** in Turkish (for the operations team), generated by template from the trace.

## Where Jev is used, and what stays deterministic

Jev is a decision model: it answers choice and yes/no questions with probabilities and does not
produce text or numbers. Every answer it gives is returned in `jev_calls`.

| Step | Question to Jev | When it is called |
|---|---|---|
| Order interpretation | Which catalog cargo type / container size does this text describe? (`Choice`, with a `not_stated` label) | When a field is missing and the regex did not find it, or when the order has a description and a cargo type was entered (checked, never overridden) |
| Compatibility | Do this order (with its description) and this carrier's description conflict? (`Noul`, one per carrier, batched) | Every eligible carrier when the order has a description; otherwise only carriers whose description may restrict |
| Requested carrier | Which carrier, if any, does the order description ask for? (`Choice` over every carrier name, in the same request) | When the order has a description |
| Carrier pre-check | Does this description restrict which orders the carrier accepts? (`Noul`) | Once, when a changed carrier description is saved. The probability is stored and compared with the current threshold at every quote, so changing `confidence.auto_accept` applies to old notes too, on the carriers page as well |

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
compared (685 measured for three); the cargo question with its four labels measured 385–395 (2026-11-16).
Questions are batched: at most one request to interpret or check an order and one for all candidates, so a
quote with a description makes two. Structured orders without a description, against carriers without
restrictive descriptions, make **no** Jev call (the seven case orders included).

Every quote reports what it cost in `jev_usage`: requests answered, their billable input tokens (as the
API reports them; failed requests are not counted), the model that answered and how many answers came
from memory. The quote page shows the same line above the Jev table, and every Jev request writes one
INFO log line (`make logs`).

A question Jev has already answered is not paid for again (`app/clients/jev_cache.py`). The key is
everything the request sends: the order fields and note, the eligible carriers' descriptions, the
carrier names and the questions themselves, so changing any text or prompt makes a new question and an
answer is never reused for something Jev was not asked. Prices, rules and distances are not part of an
answer: pressing "Teklif al" twice after a rule change asks Jev once and still shows the new ranking.
Answers live in the process's memory (up to 1,000, least recently used out first), for 24 hours and only
while the model that gave them is the one that answered last: `JEV_MODEL` pins `jev-1.14.0`, but the API was
not shown to refuse a model name it does not know. If another version answers, the quote says so in `warnings`.
The confirmation round trip relies on this memory: the resent order asks the same cargo question for free.

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
| Missing field, Jev answers `not_stated` | Not guessed: `needs_input` |
| Entered cargo type, the description read as another type with confidence ≥ 0.60 (the level at which Jev would fill an empty field) | `needs_confirmation`: no carrier, no distance, no further Jev request. Resent with `confirm_mismatch: true`: the entered value is used, the mismatch is a warning, carriers are checked against the description as usual, and `needs_review` if the description read as Hazardous |
| Entered container size, another size stated in the description | The same confirmation (parsed, no Jev request); both mismatches share one question |
| Entered cargo type, the description names no cargo (`not_stated`) or Jev is unsure (< 0.60) | No question; P(Hazardous) ≥ 0.15 still means `needs_review` |
| Jev unavailable (timeout, auth, quota) or not configured | Missing fields → `needs_input`; an order description (including an entered cargo type it could not be checked against) or restrictive carrier descriptions → `needs_review`. The ranking is kept and nothing is silently skipped. After a failure Jev is not asked for 30 s, so an outage costs one timeout (~10 s with the one retry), not one per quote |
| A container count in the description ("3 adet", "2x40HC") | Price for one container, status `needs_review` with a warning (no Jev request) |
| Approximate distance within 10% of the limit of a carrier that passes every other constraint | `needs_review`: the real road distance could change eligibility. A carrier that is out anyway (wrong size or cargo type) does not trigger it |

## Distance

The case gives an approximate table of seven routes and allows a geocoding/distance API for the rest.
The rules:

1. **The case table always wins.** Its pairs never reach the routing service, in either direction and
   under any spelling (`Ft. Lauderdale`, `MIAMI, FL`); a test makes every pair fail if a request is sent.
2. **A route outside the table is asked once and stored**, so the same pair gives the same answer later.
3. **US cities only, never guessed** (see [Cities](#cities) below).
4. **Every distance says where it came from**, the HQ distances in the ranking too.

`DistanceProvider` tries, in order:

1. Same city → 0
2. The case's table (`config/distances.yaml`, symmetric). Re-read on the next request after an edit,
   so a pair added during a demo applies without a restart; a broken edit keeps the last good table
   and the quote shows a warning (a broken file at startup fails fast)
3. PostgreSQL cache of earlier routing results (A–B and B–A share one row)
4. OpenRouteService driving distance (if `ORS_API_KEY` is set)
5. Haversine × 1.2; flagged `approximate: true`

`source` in the response is `same_city`, `case_table`, `cache`, `ors` or `haversine`; the screen shows
it in Turkish. HQ → origin distances (for the tie-break) use the same chain, are only looked up when
more than one carrier is eligible, and carry their own `hq_distance_source`.

Why not take every distance from the API? Measured once (2026-11-12, 7 ORS requests):

| Route | Case table | ORS road distance | Difference |
|---|---|---|---|
| Miami – Fort Lauderdale | 30 | 29.1 | −3.0% |
| Miami – Orlando | 235 | 235.6 | +0.3% |
| Miami – Atlanta | 660 | 663.4 | +0.5% |
| Jacksonville – Savannah | 140 | 139.2 | −0.6% |
| Tampa – Jacksonville | 200 | 198.7 | −0.6% |
| Miami – Houston | 1190 | 1188.2 | −0.2% |
| Tampa – Orlando | 85 | 84.2 | −0.9% |

The map agrees within 3%, yet with these numbers 6 of the 7 case orders get a different price (the
same winner): order 2 would cost $94.24 instead of $94.00. Distance limits sit on table values too
(A-Logistics: up to 200 miles, Tampa – Jacksonville: 200), so the table is the contract and the API
only fills the gaps.

## Cities

A city is resolved once, when an order or a carrier is saved, to a known US city:

1. The case catalog (`cities.csv` + `city_aliases.yaml`: `Ft. Lauderdale`, `NYC`, `JAX`)
2. `config/us_cities.csv`: 5,105 US cities and towns with 5,000+ people (GeoNames, CC BY 4.0), kept
   only if the US Census Bureau lists them as a place (public domain), so no neighbourhoods. One row
   per name, the most populous: Portland is Portland, OR; Manhattan is Manhattan, KS
3. The `cities` table: towns found earlier through OpenRouteService
4. OpenRouteService geocoding (US, localities only), accepted **only if the name is exactly the one
   typed**; stored, so the next time it is local

Otherwise `422 UNKNOWN_LOCATION` with suggestions, before any Jev tokens are spent:

```json
{"error": "UNKNOWN_LOCATION", "detail": "location not found: Tamap (did you mean: Tampa, FL?)",
 "city": "Tamap", "problem": "not_found", "suggestions": [{"name": "Tampa", "state": "FL"}]}
```

| `problem` | Example | Answer |
|---|---|---|
| `not_found` | `Tamap`, `Jacksonvile` | Similar spellings (`difflib`): Tampa, FL / Jacksonville, FL |
| `outside_us` | `Amsterdam, Netherlands` | Only US cities; the US city of that name: Amsterdam, NY |
| `other_state` | `Portland, ME` | Cities are known by name; this name is Portland, OR |
| `unverified` | any unknown town while ORS is down or not configured | Similar spellings, if any |

A state after a comma may be a code or a name (`Miami, FL`, `Miami, Florida`) and must be the city's.
The quote shows the resolved city with its state (`Paris` → `Paris, TX`), so nothing is silent. The
carrier form shows the same message under the HQ city field.

## City suggestions

The HQ city, origin and destination inputs open a list of up to 5 cities while you type
(`app/static/city-autocomplete.js`, a server-rendered list from `GET /admin/cities/suggest`):

- Names that **start** with the typed letters come first, the most populous first: `a` → Austin,
  Albuquerque, Atlanta, Arlington, Aurora; `ams` → Amsterdam (NY). From 3 letters on, a later word
  may also match, in the rows left over (`lauderdale` → … Fort **Lauderdale**). Joining words in lower
  case (`at`, `by`, `the`) never match, and letters in the middle of a word never do.
- Matching ignores case, dots, accents and extra spaces (`ORL`, `st. l`, `canon` → Cañon City; a
  Turkish `İ` counts as `i`). `Orlando, f` also filters by state.
- Shipped cities (catalog + `us_cities.csv`) come before towns found online (in OpenRouteService's
  relevance order). The typed letters are bold; online ones carry an `ORS` tag.
- OpenRouteService autocomplete (`layers=locality`, US only: cities and towns, never districts,
  streets or venues) is asked **only when nothing local matches** and at least 3 letters are typed.
  What it returns is stored, so the same town comes from the database next time.
- Quota guards: 250 ms debounce with the older request aborted, each query sent once per process, a
  shorter query whose answer was complete covers longer ones, 3 s timeout, 60 s pause after a failure.
- Up/Down move, Enter picks (an open list never submits the form), Escape closes. Picking is optional;
  typed text goes through the same city check as everything else.

`scripts/build_us_cities.py` rebuilds `us_cities.csv` from the two public files (~7 MB download).

## Home page

`/` shows every carrier as the same truck photo with the carrier's name lettered on the trailer
(`app/controllers/home_controller.py`, `app/views/showroom.py`, `templates/home/index.html`,
`static/home/`). It reads `CarrierService.list()` and nothing else, so it never calls Jev or
OpenRouteService, and a carrier added on the admin screen appears as a new truck on the next load.

- **Markings in perspective.** Each fact is painted where a real truck carries that kind of information:
  the name with the rate under it on the curtain, a container-size stencil at the curtain's rear corner,
  cargo badges stacked on its front edge (with a diamond placard only for Hazardous), and the home city with the
  distance range on the cab door. The curtain (1000 × 200 units, about 5:1) and the door (300 × 270) are
  HTML boxes mapped onto their four measured corners with CSS `matrix3d` homographies computed on the
  server, so the page is right before any script runs; the script only shrinks text to fit. Each card is
  laid out at the photo's pixel size and scaled as a whole, which keeps the markings in place at any width.
- **Images.** `scene.jpg` is the reference photo with its logo removed; `truck.webp` is the same truck
  cut out of it (Apple Vision foreground mask), so the two line up pixel for pixel; `scene-blur.jpg` is
  the pre-blurred backdrop. Using another photo means measuring `SCENE_PANEL`, `SCENE_DOOR` and
  `TRUCK_ORIGIN` again (unit tests check that the matrices land on the measured corners).
- **Showroom.** Drag, wheel/trackpad, swipe or ← → move the row with momentum; the centre truck is the
  active carrier and drives the headline, counter, colour and URL hash (`#firma-<id>`, so a reload keeps
  it). Clicking a side truck flies it to the centre; clicking the centre truck opens its detail view,
  where the same truck lands in the full photo and the camera moves between four facts: rate, distance
  range, container sizes, cargo types (plus the carrier's note, if any). The camera only goes where that
  fact is painted: each facet's camera box is its marking's projected corners plus a margin, a unit test
  checks that every camera contains its marking, and the marking lights up when the camera arrives while
  the others step back. × or Escape returns to the same carrier.
- **Colour.** Each carrier gets one of 8 accents from a hash of its name (stable across database resets;
  no column). A carrier change sends a radial noise wave through the background: a small WebGL shader
  ported from the Codrops demo "Model Texture Transition and Procedural Radial Noise using WebGL" (MIT)
  with Stefan Gustavson's Perlin noise, drawn only while the wave runs. Without WebGL a CSS glow is used.
- No libraries and no build step (plain JS and CSS, no CDN). Without JavaScript the page is a scrollable
  row of trucks with their facts; `prefers-reduced-motion` turns the motion into plain cuts.

## API

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/quotes` | Business outcomes (including "no carrier") are `200` with a `status` |
| GET, POST | `/api/v1/carriers` | `409 DUPLICATE_CARRIER` for a duplicate name (case-insensitive) |
| GET, PUT, DELETE | `/api/v1/carriers/{id}` | `404 CARRIER_NOT_FOUND` |
| GET | `/api/v1/cities?q=orl&limit=5` | City suggestions `{"items": [{"name", "state", "source"}], "warnings": []}`; `limit` 1–10 |
| GET | `/health` | Includes a database probe |

A description that contradicts an entered field is a business outcome too: `200` with
`"status": "needs_confirmation"` and a `confirmation` object; resend the same order with
`"confirm_mismatch": true` to go on (the admin screen shows the question with a checkbox that does this):

```json
"confirmation": {"message": "Girilen yük tipi ile açıklama uyumsuz. Bu şekilde devam etmek istiyor musunuz?",
  "mismatches": [{"field": "cargo_type", "entered": "Dry", "described": "Hazardous", "confidence": 0.93, "source": "jev"}]}
```

Errors are `{"error": CODE, "detail": ...}`: `UNKNOWN_LOCATION` (with `problem` and `suggestions`,
see [Cities](#cities)), `INVALID_ORDER`, `INVALID_CARRIER` (422; an unknown HQ city is a field error
with a suggestion), `INVALID_RULES` (500, only when `rules.yaml` has never been valid since the
app started; a broken edit keeps the last valid rules and adds a warning). Unknown request fields
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
  "jev_usage": {"requests": 0, "input_tokens": 0, "model": null, "cached": 0},
  "warnings": [],
  "explanation": "Rota Miami → Atlanta: 660 mil; 20 ft, Reefer. B-Logistics seçildi: toplam $660.00 (660 mil × $1.00/mil). Toplam ücret eşit; belirleyici kriter: merkezin çıkış noktasına uzaklığı — B-Logistics: 30 mil (Fort Lauderdale), M-Logistics: 1190 mil (Houston). Elenenler: ..."
}
```

Money and miles are decimals serialized as strings, so nothing is rounded through a float.

## Tests

| Layer | What it checks | DB | Network | Jev |
|---|---|---|---|---|
| `tests/unit/selection` | The 7 case orders, inclusive limits (200/250/300), tie-breaks, ranking swap via config, rules validation, explanations, when a description contradicts an entered field | – | – | – |
| `tests/unit/distance` | Every case-table pair without a request, city resolution and "did you mean", table reload, suggestion ranking, the US city list and its build script, ORS client (httpx MockTransport) | – | – | – |
| `tests/unit/services` | Confidence bands, hazardous asymmetry, the confirmation for a contradicted field, order/carrier compatibility, Jev outage, batching, city suggestion quota guards | – | – | fake |
| `tests/unit/clients` | The Jev client with a scripted SDK: token count and model, outage pause, the answer cache and its key | – | – | scripted |
| `tests/unit/test_showroom.py` | Home page view model: the curtain and door homographies land on the measured corners, every facet camera frames its marking, accents, carrier facts | – | – | – |
| `tests/api` | REST endpoints, the admin screen and the home page over TestClient | fake | – | fake |
| `tests/integration` | PostgreSQL repositories, CHECK constraints, the real app wiring | ✓ | – | – |
| `tests/live` | Two tiny real Jev requests (opt-in, costs tokens) | – | ✓ | real |

```bash
make test        # 453 tests, no database/network/Jev, ~2 s
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
`config/`), so no restart is needed. A broken edit (a typo, an unknown criterion) does not stop the
service: quotes keep using the last valid rules, every response carries a warning that names the
problem, and `/admin/rules` shows it until the file is fixed. Only a file that was never valid
since the app started returns `500 INVALID_RULES`.

**Change the ranking priority on screen.** `/admin/rules` lists the ranking criteria: move them up or
down, remove or add them, then save. Saving rewrites only the `ranking` block of `rules.yaml` (comments
and other sections are kept) after validating it. A criterion added in code appears there automatically.
At least one criterion must stay: with none, carriers would be chosen by name alone, so that save is refused.

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

**Add a ranking criterion from existing data** (e.g. prefer the specialist, the carrier that carries
the fewest cargo types): one entry in `app/selection/criteria.py`, then add it on `/admin/rules`.
This is a code change: in Docker run `make run` to rebuild (or use `make dev`, which reloads code
automatically).

```python
# app/selection/criteria.py
"specialist": Criterion(
    key=lambda c: (len(c.carrier.cargo_types),),
    label="uzmanlaşma (az yük tipi)",
    describe=lambda c: f"{len(c.carrier.cargo_types)} yük tipi",
),
```

A criterion changes a result only when the carriers differ on it. With the case's four carriers
`specialist` changes none of the seven results; add a cheap generalist (Miami, 40 ft, all three
cargo types, $0.30 per mile) and order 2 goes to it on price ($70.50), but to S-Logistics ($94.00)
with `specialist` first. A criterion on the rate per mile would never change anything: every
carrier drives the same miles, so it orders exactly like the total price.

**Add a criterion that needs a new carrier attribute** (e.g. a rating, higher is better). Rehearsed
end to end against PostgreSQL; in this order:

1. `db/migrations/002_add_rating.sql`, then `make migrate` (keeps the data; never `make reset-db`
   during a demo). Migrate before changing the code: the queries name the column.
   `ALTER TABLE carriers ADD COLUMN IF NOT EXISTS rating NUMERIC(2,1) NOT NULL DEFAULT 3.0;`
2. `Carrier` (`app/models/carrier.py`): the field, with its default.
3. `CarrierIn` and `CarrierOut` (`app/schemas/carrier.py`).
4. `app/repositories/carrier_repository.py`: `_COLUMNS`, `_VALUES`, the INSERT and UPDATE column
   lists, `_params`, `_to_carrier`.
5. `CarrierService._build`: pass the field on to `Carrier(...)`; without it the value is dropped.
6. `app/views/forms.py` and the templates in `app/views/templates/carriers/` (input, column).
7. Criterion with a negated key: `key=lambda c: (-c.carrier.rating,)`.
8. Add it on `/admin/rules` (or to `ranking` in `rules.yaml`), after the code is running.

**Add a hard constraint**: a function returning a Turkish reason or `None`, registered in
`CONSTRAINTS` (`app/selection/constraints.py`), and its name under `filters`.

**Add a cargo type or container size**: one line in `catalog`. Orders and carriers accept it at once.
Removing one does not change stored carriers: their edit form shows the value ticked and marked
"katalogda yok", and saving is refused until it is unticked, so an edit never drops it silently.

**Tune Jev thresholds**: the `confidence` section.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql://carrier:carrier@localhost:5433/carrier` | Host port 5433 avoids a local PostgreSQL on 5432 |
| `TYPESAFE_API_KEY` | – | Jev. Without it, free text asks for input and restrictive notes need review |
| `JEV_MODEL` | `jev-1.14.0` | The version the confidence thresholds were measured on; another answering version is reported in `warnings` |
| `JEV_TIMEOUT_SECONDS` | `5` | Per request; one retry |
| `ORS_API_KEY` | – | OpenRouteService; without it off-table routes use Haversine, suggestions stay local and only shipped or stored cities are accepted |
| `RULES_PATH` | `config/rules.yaml` | |

## Decisions

- **Python 3.12 + FastAPI**: the official Jev SDK is Python; Pydantic gives validation and Swagger
  from one model; `Decimal` is in the standard library. `.python-version` keeps uv on 3.12 like the image.
- **An entered field is never overridden by free text**: a contradiction is asked, not resolved silently in
  either direction; Jev reads the description without the entered value, so it cannot simply agree with the form.
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
- A quote prices one container. An order has no quantity field yet; a count in the description
  ("3 adet", "2x40HC", "three containers") makes the quote `needs_review` with a warning that one
  container was priced. Whether carriers have a capacity limit is not defined by the case.
- Free text (order or carrier description) can only narrow eligibility; it never re-ranks. Missing
  information is not a conflict. Price-changing notes ("+20% over 500 miles") need a structured
  field, because Jev does not do arithmetic.
- Order and carrier descriptions are sent to the Jev API; they should not contain confidential data.
- US cities only. Cities are known by name, so a name means one city: the catalog's, else the most
  populous (`Portland, ME` is refused with "this name is Portland, OR"). Supporting both would mean
  name + state as the key of carriers, cached distances and the table.
- `us_cities.csv` prefers a missing town to a wrong one: New Jersey townships and some New England
  towns are not Census places, so they come from OpenRouteService when typed (one request, then stored).
- ORS's locality layer includes census-designated places, so a town found online may be a community
  next to a city (Boca West next to Boca Raton). They are real places with coordinates.
- The distance cache never expires (road distances rarely change).
- The Jev answer cache is in memory: a restart empties it, and several app processes would not share it
  (the app runs as one process). Texts are compared exactly, so a change of case is a new question.
- The admin screen has no authentication.
