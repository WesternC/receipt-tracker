CREATE TABLE users (
	id SERIAL PRIMARY KEY,
	username VARCHAR(24) NOT NULL UNIQUE,
	password TEXT NOT NULL,
	account_creation_date TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE merchants (
	id SERIAL PRIMARY KEY,
	name TEXT NOT NULL UNIQUE,
	type TEXT NOT NULL
);

CREATE TABLE receipts (
	id SERIAL PRIMARY KEY,
	user_id INTEGER NOT NULL REFERENCES users(id),
	merchant_id INTEGER NOT NULL REFERENCES merchants(id),
	purchase_total NUMERIC(10,2),
	receipt_date DATE,
	upload_date TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE receipt_items (
	receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
	category TEXT NOT NULL,
	item TEXT NOT NULL,
	price NUMERIC(10,2) NOT NULL
);

CREATE INDEX idx_receipts_user_id ON receipts(user_id);
CREATE INDEX idx_receipt_items_receipt_id ON receipt_items(receipt_id);