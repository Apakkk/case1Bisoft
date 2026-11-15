-- The four carriers from the case. Their descriptions contain no restrictions, so they are stored
-- as note_status = 'none'; any description saved from the admin screen is pre-checked by Jev.
INSERT INTO carriers (name, hq_city, min_miles, max_miles, container_sizes, cargo_types, rate_per_mile, description, note_status)
VALUES
    ('S-Logistics', 'Tampa',           NULL, 300,  '{40,45}', '{Dry}',                  0.40,
     'Tampa-based short-haul specialist for dry cargo in Florida.', 'none'),
    ('B-Logistics', 'Fort Lauderdale', 250,  NULL, '{20}',    '{Dry,Reefer}',           1.00,
     'Long-haul lanes out of South Florida with cold-chain experience.', 'none'),
    ('A-Logistics', 'Jacksonville',    NULL, 200,  '{45}',    '{Dry,Hazardous}',        2.00,
     'North Florida and Georgia ports; certified hazmat drivers.', 'none'),
    ('M-Logistics', 'Houston',         NULL, NULL, '{20,40}', '{Dry,Reefer,Hazardous}', 1.00,
     'Nationwide network, all cargo types.', 'none');
