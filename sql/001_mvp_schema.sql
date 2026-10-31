-- Rupiverse MVP schema, version 1. Target: PostgreSQL 15+.
-- Design and rules: docs/database-schema.md (same text as ../rupiverse-mobile-mvp-schema.md).
-- Apply to an empty database:
--   psql "$STATEMENT_DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/001_mvp_schema.sql

BEGIN;

-- Keeps updated_at current on every change.
CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

-- 1. users
CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email varchar(320) NOT NULL CHECK (email = btrim(email) AND email <> ''),
  display_name varchar(120) NOT NULL CHECK (btrim(display_name) <> ''),
  base_currency char(3) NOT NULL DEFAULT 'INR' CHECK (base_currency ~ '^[A-Z]{3}$'),
  timezone text NOT NULL DEFAULT 'Asia/Kolkata' CHECK (timezone <> ''),
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by uuid REFERENCES users (id),
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by uuid REFERENCES users (id),
  deleted_at timestamptz,
  deleted_by uuid REFERENCES users (id),
  CONSTRAINT users_deleted_pair CHECK (deleted_at IS NOT NULL OR deleted_by IS NULL)
);
CREATE UNIQUE INDEX users_email_active_key ON users (lower(email)) WHERE deleted_at IS NULL;

-- 2. accounts
CREATE TABLE accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id),
  display_name varchar(100) NOT NULL CHECK (btrim(display_name) <> ''),
  account_type text NOT NULL CHECK (account_type IN ('bank', 'credit_card', 'cash', 'wallet', 'investment', 'other')),
  account_purpose text CHECK (account_purpose IN ('salary', 'savings', 'expense', 'general', 'other')),
  institution_name varchar(100),
  account_last4 char(4) CHECK (account_last4 ~ '^[0-9]{4}$'),
  currency char(3) NOT NULL DEFAULT 'INR' CHECK (currency ~ '^[A-Z]{3}$'),
  opening_balance numeric(14, 2) NOT NULL DEFAULT 0,
  opening_balance_date date,
  current_balance numeric(14, 2),
  balance_as_of date,
  last_synced_at timestamptz,
  balance_source text CHECK (balance_source IN ('statement', 'calculated', 'manual')),
  is_archived boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by uuid REFERENCES users (id),
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by uuid REFERENCES users (id),
  deleted_at timestamptz,
  deleted_by uuid REFERENCES users (id),
  CONSTRAINT accounts_user_id_key UNIQUE (user_id, id),
  CONSTRAINT accounts_deleted_pair CHECK (deleted_at IS NOT NULL OR deleted_by IS NULL)
);
CREATE INDEX accounts_list_idx ON accounts (user_id, is_archived, display_name) WHERE deleted_at IS NULL;

-- 3. account_tags
CREATE TABLE account_tags (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id),
  account_id uuid NOT NULL,
  tag varchar(40) NOT NULL CHECK (btrim(tag) <> '' AND tag = btrim(tag)),
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by uuid REFERENCES users (id),
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by uuid REFERENCES users (id),
  deleted_at timestamptz,
  deleted_by uuid REFERENCES users (id),
  CONSTRAINT account_tags_user_id_key UNIQUE (user_id, id),
  CONSTRAINT account_tags_account_fk FOREIGN KEY (user_id, account_id) REFERENCES accounts (user_id, id),
  CONSTRAINT account_tags_deleted_pair CHECK (deleted_at IS NOT NULL OR deleted_by IS NULL)
);
CREATE UNIQUE INDEX account_tags_active_key ON account_tags (user_id, account_id, lower(tag)) WHERE deleted_at IS NULL;
CREATE INDEX account_tags_account_idx ON account_tags (user_id, account_id) WHERE deleted_at IS NULL;

-- 4. categories
CREATE TABLE categories (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id),
  parent_id uuid,
  name varchar(60) NOT NULL CHECK (btrim(name) <> ''),
  flow_type text NOT NULL CHECK (flow_type IN ('income', 'expense')),
  created_via text NOT NULL CHECK (created_via IN ('system', 'user', 'ai')),
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by uuid REFERENCES users (id),
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by uuid REFERENCES users (id),
  deleted_at timestamptz,
  deleted_by uuid REFERENCES users (id),
  CONSTRAINT categories_user_id_key UNIQUE (user_id, id),
  CONSTRAINT categories_parent_fk FOREIGN KEY (user_id, parent_id) REFERENCES categories (user_id, id),
  CONSTRAINT categories_not_own_parent CHECK (parent_id IS NULL OR parent_id <> id),
  CONSTRAINT categories_deleted_pair CHECK (deleted_at IS NOT NULL OR deleted_by IS NULL)
);
-- Names are unique per user, parent and flow (case-insensitive). Top-level rows use a nil UUID as the parent.
CREATE UNIQUE INDEX categories_name_active_key ON categories (
  user_id, COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'::uuid), flow_type, lower(name)
) WHERE deleted_at IS NULL;
CREATE INDEX categories_picker_idx ON categories (user_id, flow_type, parent_id, name) WHERE deleted_at IS NULL;

CREATE FUNCTION categories_check_parent_flow() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.parent_id IS NOT NULL AND EXISTS (
    SELECT 1 FROM categories AS p
    WHERE p.user_id = NEW.user_id AND p.id = NEW.parent_id AND p.flow_type <> NEW.flow_type
  ) THEN
    RAISE EXCEPTION 'a child category must have the same flow_type as its parent';
  END IF;
  RETURN NEW;
END;
$$;

-- 5. merchants
CREATE TABLE merchants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id),
  display_name varchar(120) NOT NULL CHECK (btrim(display_name) <> ''),
  normalized_name varchar(120) NOT NULL CHECK (btrim(normalized_name) <> ''),
  default_category_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by uuid REFERENCES users (id),
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by uuid REFERENCES users (id),
  deleted_at timestamptz,
  deleted_by uuid REFERENCES users (id),
  CONSTRAINT merchants_user_id_key UNIQUE (user_id, id),
  CONSTRAINT merchants_default_category_fk FOREIGN KEY (user_id, default_category_id) REFERENCES categories (user_id, id),
  CONSTRAINT merchants_deleted_pair CHECK (deleted_at IS NOT NULL OR deleted_by IS NULL)
);
CREATE UNIQUE INDEX merchants_normalized_active_key ON merchants (user_id, normalized_name) WHERE deleted_at IS NULL;

-- 6. statement_imports
CREATE TABLE statement_imports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id),
  account_id uuid,
  file_sha256 char(64) NOT NULL CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
  file_format text NOT NULL CHECK (file_format IN ('pdf', 'csv', 'xlsx')),
  statement_type text NOT NULL CHECK (statement_type IN ('bank', 'credit_card', 'mixed', 'unknown')),
  period_from date,
  period_to date,
  status text NOT NULL CHECK (status IN ('processing', 'needs_review', 'completed', 'failed', 'cancelled')),
  row_count integer NOT NULL DEFAULT 0 CHECK (row_count >= 0),
  error_message text,
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by uuid REFERENCES users (id),
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by uuid REFERENCES users (id),
  deleted_at timestamptz,
  deleted_by uuid REFERENCES users (id),
  CONSTRAINT statement_imports_user_id_key UNIQUE (user_id, id),
  CONSTRAINT statement_imports_account_fk FOREIGN KEY (user_id, account_id) REFERENCES accounts (user_id, id),
  CONSTRAINT statement_imports_period_order CHECK (period_from IS NULL OR period_to IS NULL OR period_from <= period_to),
  CONSTRAINT statement_imports_deleted_pair CHECK (deleted_at IS NOT NULL OR deleted_by IS NULL)
);
-- Not unique: a re-import of the same file is allowed, and the app asks the user what to do.
CREATE INDEX statement_imports_sha_idx ON statement_imports (user_id, file_sha256) WHERE deleted_at IS NULL;

-- 7. import_rows (transaction_id gets its foreign key after transactions exists)
CREATE TABLE import_rows (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id),
  import_id uuid NOT NULL,
  row_number integer NOT NULL CHECK (row_number > 0),
  account_id uuid,
  transaction_date date NOT NULL,
  transaction_time time,
  posted_date date,
  description_raw text,
  merchant_id uuid,
  amount numeric(14, 2) NOT NULL CHECK (amount > 0),
  currency char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
  direction text NOT NULL CHECK (direction IN ('debit', 'credit')),
  balance_after numeric(14, 2),
  suggested_type text CHECK (suggested_type IN ('expense', 'income', 'transfer')),
  suggested_category_id uuid,
  category_source text CHECK (category_source IN ('import', 'rule', 'merchant_memory', 'ai')),
  category_confidence numeric(4, 3) CHECK (category_confidence BETWEEN 0 AND 1),
  review_status text NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'needs_review', 'accepted', 'skipped')),
  transaction_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by uuid REFERENCES users (id),
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by uuid REFERENCES users (id),
  deleted_at timestamptz,
  deleted_by uuid REFERENCES users (id),
  CONSTRAINT import_rows_user_id_key UNIQUE (user_id, id),
  CONSTRAINT import_rows_row_key UNIQUE (user_id, import_id, row_number),
  CONSTRAINT import_rows_import_fk FOREIGN KEY (user_id, import_id) REFERENCES statement_imports (user_id, id),
  CONSTRAINT import_rows_account_fk FOREIGN KEY (user_id, account_id) REFERENCES accounts (user_id, id),
  CONSTRAINT import_rows_merchant_fk FOREIGN KEY (user_id, merchant_id) REFERENCES merchants (user_id, id),
  CONSTRAINT import_rows_suggested_category_fk FOREIGN KEY (user_id, suggested_category_id) REFERENCES categories (user_id, id),
  CONSTRAINT import_rows_deleted_pair CHECK (deleted_at IS NOT NULL OR deleted_by IS NULL)
);
CREATE INDEX import_rows_review_idx ON import_rows (user_id, import_id, review_status, row_number) WHERE deleted_at IS NULL;

-- 8. transactions
CREATE TABLE transactions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id),
  transaction_type text NOT NULL CHECK (transaction_type IN ('expense', 'income', 'transfer')),
  transfer_kind text CHECK (transfer_kind IN ('interbank', 'account_transfer', 'credit_card_payment', 'cash_withdrawal', 'other')),
  amount numeric(14, 2) NOT NULL CHECK (amount > 0),
  currency char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
  transaction_date date NOT NULL,
  transaction_time time,
  posted_date date,
  account_id uuid NOT NULL,
  counter_account_id uuid,
  category_id uuid,
  merchant_id uuid,
  description varchar(200),
  transaction_source text NOT NULL CHECK (transaction_source IN ('manual', 'statement_import', 'other')),
  import_row_id uuid,
  category_source text CHECK (category_source IN ('manual', 'rule', 'merchant_memory', 'ai', 'import')),
  ai_suggested_category_id uuid,
  ai_confidence numeric(4, 3) CHECK (ai_confidence BETWEEN 0 AND 1),
  linked_transaction_id uuid,
  note text,
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by uuid REFERENCES users (id),
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by uuid REFERENCES users (id),
  deleted_at timestamptz,
  deleted_by uuid REFERENCES users (id),
  CONSTRAINT transactions_user_id_key UNIQUE (user_id, id),
  -- Transfers name a second account and no category; every other type has neither.
  CONSTRAINT transactions_transfer_shape CHECK (
    (transaction_type = 'transfer' AND transfer_kind IS NOT NULL AND counter_account_id IS NOT NULL
      AND counter_account_id <> account_id AND category_id IS NULL)
    OR (transaction_type <> 'transfer' AND transfer_kind IS NULL AND counter_account_id IS NULL)
  ),
  CONSTRAINT transactions_account_fk FOREIGN KEY (user_id, account_id) REFERENCES accounts (user_id, id),
  CONSTRAINT transactions_counter_account_fk FOREIGN KEY (user_id, counter_account_id) REFERENCES accounts (user_id, id),
  CONSTRAINT transactions_category_fk FOREIGN KEY (user_id, category_id) REFERENCES categories (user_id, id),
  CONSTRAINT transactions_merchant_fk FOREIGN KEY (user_id, merchant_id) REFERENCES merchants (user_id, id),
  CONSTRAINT transactions_ai_category_fk FOREIGN KEY (user_id, ai_suggested_category_id) REFERENCES categories (user_id, id),
  CONSTRAINT transactions_linked_fk FOREIGN KEY (user_id, linked_transaction_id) REFERENCES transactions (user_id, id),
  CONSTRAINT transactions_import_row_fk FOREIGN KEY (user_id, import_row_id) REFERENCES import_rows (user_id, id),
  CONSTRAINT transactions_deleted_pair CHECK (deleted_at IS NOT NULL OR deleted_by IS NULL)
);
-- One accepted staging row cannot create two ledger rows.
CREATE UNIQUE INDEX transactions_import_row_key ON transactions (user_id, import_row_id) WHERE import_row_id IS NOT NULL;
CREATE INDEX transactions_date_idx ON transactions (user_id, transaction_date DESC) WHERE deleted_at IS NULL;
CREATE INDEX transactions_type_idx ON transactions (user_id, transaction_type, transaction_date) WHERE deleted_at IS NULL;
CREATE INDEX transactions_category_idx ON transactions (user_id, category_id, transaction_date) WHERE deleted_at IS NULL;
CREATE INDEX transactions_account_idx ON transactions (user_id, account_id, transaction_date) WHERE deleted_at IS NULL;
CREATE INDEX transactions_merchant_idx ON transactions (user_id, merchant_id, transaction_date) WHERE deleted_at IS NULL;

CREATE FUNCTION transactions_check_category_flow() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.category_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM categories AS c
    WHERE c.user_id = NEW.user_id AND c.id = NEW.category_id AND c.flow_type = NEW.transaction_type
  ) THEN
    RAISE EXCEPTION 'a transaction category must have the same flow_type as the transaction';
  END IF;
  RETURN NEW;
END;
$$;

-- The rows of import_rows point at accepted transactions, which are defined above.
ALTER TABLE import_rows
  ADD CONSTRAINT import_rows_transaction_fk FOREIGN KEY (user_id, transaction_id) REFERENCES transactions (user_id, id);

-- Keeps updated_at current on every change.
CREATE TRIGGER users_set_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER accounts_set_updated_at BEFORE UPDATE ON accounts FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER account_tags_set_updated_at BEFORE UPDATE ON account_tags FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER categories_set_updated_at BEFORE UPDATE ON categories FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER merchants_set_updated_at BEFORE UPDATE ON merchants FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER statement_imports_set_updated_at BEFORE UPDATE ON statement_imports FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER import_rows_set_updated_at BEFORE UPDATE ON import_rows FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER transactions_set_updated_at BEFORE UPDATE ON transactions FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER categories_parent_flow BEFORE INSERT OR UPDATE OF parent_id, flow_type ON categories
  FOR EACH ROW EXECUTE FUNCTION categories_check_parent_flow();
CREATE TRIGGER transactions_category_flow BEFORE INSERT OR UPDATE OF category_id, transaction_type ON transactions
  FOR EACH ROW EXECUTE FUNCTION transactions_check_category_flow();

COMMIT;
