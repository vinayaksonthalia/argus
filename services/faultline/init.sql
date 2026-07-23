CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    price_cents INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO products (name, price_cents) VALUES
    ('Anti-Entropy Umbrella', 4999),
    ('Self-Healing Mug', 2199),
    ('Observability Candle (p99 scent)', 1499),
    ('Chaos Monkey Plush', 3499),
    ('Root Cause Analysis Board Game', 5999),
    ('Distributed Tracing Yarn Kit', 1899),
    ('Idempotency Key Ring', 999),
    ('Cardinality Explosion Party Popper', 799),
    ('Golden Signals Desk Flag Set', 2499),
    ('Retry Storm Snow Globe', 3299)
ON CONFLICT DO NOTHING;
