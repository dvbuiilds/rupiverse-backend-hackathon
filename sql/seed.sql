-- Dummy seed data for local development. Idempotent: safe to run again.
-- Apply after sql/001_mvp_schema.sql:
--   psql "$STATEMENT_DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/seed.sql

BEGIN;

INSERT INTO users (id, email, display_name)
VALUES ('00000000-0000-0000-0000-000000000001', 'demo@rupiverse.local', 'Demo User')
ON CONFLICT (id) DO NOTHING;

-- Card accounts. last4 is left empty on purpose: set it locally to turn on the card-number cross-check.
INSERT INTO accounts (id, user_id, display_name, account_type, institution_name, opening_balance_date) VALUES
  ('00000000-0000-0000-0000-0000000000c1', '00000000-0000-0000-0000-000000000001', 'HDFC Swiggy', 'credit_card', 'HDFC Bank', '2026-01-01'),
  ('00000000-0000-0000-0000-0000000000c2', '00000000-0000-0000-0000-000000000001', 'Axis Supermoney', 'credit_card', 'Axis Bank', '2026-01-01'),
  ('00000000-0000-0000-0000-0000000000c3', '00000000-0000-0000-0000-000000000001', 'PNB Kiwi', 'credit_card', 'PNB', '2026-01-01'),
  ('00000000-0000-0000-0000-0000000000c4', '00000000-0000-0000-0000-000000000001', 'Scapia', 'credit_card', 'Federal Bank', '2026-01-01'),
  ('00000000-0000-0000-0000-0000000000c5', '00000000-0000-0000-0000-000000000001', 'YES Bank Uni', 'credit_card', 'YES Bank', '2026-01-01')
ON CONFLICT (id) DO NOTHING;

-- Placeholder account for card bill payments (the other side of a transfer).
INSERT INTO accounts (id, user_id, display_name, account_type)
VALUES ('00000000-0000-0000-0000-0000000000a0', '00000000-0000-0000-0000-000000000001', 'Unlinked account', 'other')
ON CONFLICT (id) DO NOTHING;

INSERT INTO categories (id, user_id, name, slug, color, flow_type, created_via) VALUES
  ('00000000-0000-0000-0000-0000000000d1', '00000000-0000-0000-0000-000000000001', 'Food & groceries', 'food', '#B5460F', 'expense', 'system'),
  ('00000000-0000-0000-0000-0000000000d2', '00000000-0000-0000-0000-000000000001', 'Transport', 'transport', '#1F5A50', 'expense', 'system'),
  ('00000000-0000-0000-0000-0000000000d3', '00000000-0000-0000-0000-000000000001', 'Rent', 'rent', '#6B4E9B', 'expense', 'system'),
  ('00000000-0000-0000-0000-0000000000d4', '00000000-0000-0000-0000-000000000001', 'Bills & utilities', 'bills', '#2E6DA4', 'expense', 'system'),
  ('00000000-0000-0000-0000-0000000000d5', '00000000-0000-0000-0000-000000000001', 'Shopping', 'shopping', '#B03A6B', 'expense', 'system'),
  ('00000000-0000-0000-0000-0000000000d6', '00000000-0000-0000-0000-000000000001', 'Subscriptions', 'subscriptions', '#5C6B2E', 'expense', 'system'),
  ('00000000-0000-0000-0000-0000000000d7', '00000000-0000-0000-0000-000000000001', 'Entertainment', 'entertainment', '#C0841A', 'expense', 'system'),
  ('00000000-0000-0000-0000-0000000000d8', '00000000-0000-0000-0000-000000000001', 'Health', 'health', '#2F7D4F', 'expense', 'system'),
  ('00000000-0000-0000-0000-0000000000d9', '00000000-0000-0000-0000-000000000001', 'Travel', 'travel', '#3A6E8F', 'expense', 'system'),
  ('00000000-0000-0000-0000-0000000000da', '00000000-0000-0000-0000-000000000001', 'Fees & charges', 'fees', '#8A4B4B', 'expense', 'system'),
  ('00000000-0000-0000-0000-0000000000db', '00000000-0000-0000-0000-000000000001', 'Cash & ATM', 'cash', '#5E5E5E', 'expense', 'system'),
  ('00000000-0000-0000-0000-0000000000dc', '00000000-0000-0000-0000-000000000001', 'Other expenses', 'other_expense', '#7A7A7A', 'expense', 'system'),
  ('00000000-0000-0000-0000-0000000000dd', '00000000-0000-0000-0000-000000000001', 'Salary', 'salary', '#1E7B3A', 'income', 'system'),
  ('00000000-0000-0000-0000-0000000000de', '00000000-0000-0000-0000-000000000001', 'Refunds', 'refunds', '#2A8C8C', 'income', 'system'),
  ('00000000-0000-0000-0000-0000000000df', '00000000-0000-0000-0000-000000000001', 'Interest & investment income', 'interest', '#4C8C2A', 'income', 'system'),
  ('00000000-0000-0000-0000-0000000000e0', '00000000-0000-0000-0000-000000000001', 'Other income', 'other_income', '#6E8C2A', 'income', 'system')
ON CONFLICT (id) DO NOTHING;

COMMIT;
