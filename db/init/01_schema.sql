-- Runs once on an empty volume (docker-entrypoint-initdb.d). Later changes go to db/migrations/.

CREATE TABLE carriers (
    id               INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name             TEXT NOT NULL,
    hq_city          TEXT NOT NULL,
    min_miles        NUMERIC(8, 1),               -- NULL = no lower bound
    max_miles        NUMERIC(8, 1),               -- NULL = no upper bound
    container_sizes  SMALLINT[] NOT NULL,
    cargo_types      TEXT[] NOT NULL,             -- allowed values live in config/rules.yaml (catalog)
    rate_per_mile    NUMERIC(10, 4) NOT NULL,
    description      TEXT NOT NULL DEFAULT '',    -- free text, editable on the admin screen
    note_status      TEXT NOT NULL DEFAULT 'none',
    note_confidence  NUMERIC(4, 3),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT carriers_name_not_blank   CHECK (btrim(name) <> ''),
    CONSTRAINT carriers_hq_not_blank     CHECK (btrim(hq_city) <> ''),
    CONSTRAINT carriers_rate_positive    CHECK (rate_per_mile > 0),
    CONSTRAINT carriers_miles_positive   CHECK (coalesce(min_miles, 0) >= 0 AND coalesce(max_miles, 0) >= 0),
    CONSTRAINT carriers_miles_range      CHECK (min_miles IS NULL OR max_miles IS NULL OR min_miles <= max_miles),
    CONSTRAINT carriers_sizes_not_empty  CHECK (cardinality(container_sizes) > 0),
    CONSTRAINT carriers_cargo_not_empty  CHECK (cardinality(cargo_types) > 0),
    CONSTRAINT carriers_note_status      CHECK (note_status IN ('none', 'constraint', 'unchecked')),
    CONSTRAINT carriers_note_confidence  CHECK (note_confidence IS NULL OR note_confidence BETWEEN 0 AND 1)
);

-- Carrier names are unique regardless of case ("M-Logistics" = "m-logistics").
CREATE UNIQUE INDEX carriers_name_unique ON carriers (lower(name));

-- Routing-API results, so each off-table route is fetched once. A-B and B-A share one row.
CREATE TABLE distance_cache (
    city_a      TEXT NOT NULL,
    city_b      TEXT NOT NULL,
    miles       NUMERIC(8, 1) NOT NULL CHECK (miles >= 0),
    source      TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (city_a, city_b),
    CONSTRAINT distance_cache_ordered CHECK (city_a < city_b)
);
