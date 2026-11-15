-- Cities found through OpenRouteService autocomplete (the shipped catalog stays in config/cities.csv).
-- Stored so the next suggestion comes from the database and the distance chain needs no geocoding call.
-- Idempotent: `make migrate` runs it on every start and keeps existing rows.

SET client_min_messages = warning;  -- no "already exists, skipping" notices on re-runs

CREATE TABLE IF NOT EXISTS cities (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT '',     -- two-letter US state code, '' if ORS did not say
    lat         DOUBLE PRECISION NOT NULL,
    lon         DOUBLE PRECISION NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT cities_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT cities_lat_range      CHECK (lat BETWEEN -90 AND 90),
    CONSTRAINT cities_lon_range      CHECK (lon BETWEEN -180 AND 180)
);

-- The rest of the system knows a city by its name only, so one row per name (first one found wins).
CREATE UNIQUE INDEX IF NOT EXISTS cities_name_unique ON cities (lower(name));
