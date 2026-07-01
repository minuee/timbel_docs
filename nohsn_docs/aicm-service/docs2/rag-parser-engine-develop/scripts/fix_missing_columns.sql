-- Fix: missing ORM columns not covered by prior migrations (2026-05-21)
-- Run this SQL directly on the PostgreSQL DB if alembic upgrade is not available.
-- All statements use IF NOT EXISTS -- safe to run multiple times.

-- 1. repositories: add missing columns
ALTER TABLE repositories
  ADD COLUMN IF NOT EXISTS search_mode    VARCHAR(20) NOT NULL DEFAULT 'simple',
  ADD COLUMN IF NOT EXISTS display_config JSONB       NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS llm_config     JSONB       NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS agent_id       UUID,
  ADD COLUMN IF NOT EXISTS namespace      TEXT;

-- 2. api_keys: add missing column
ALTER TABLE api_keys
  ADD COLUMN IF NOT EXISTS created_by UUID;

-- 3. seed default Lucas-KMS tenant (LUCAS_AUTH_DISABLED=true mode requires this)
INSERT INTO tenants (
    id, name, slug, config, plan, tenant_type, context_config, feature_flags
) VALUES (
    '00000000-0000-0000-0000-000000000001',
    'Lucas-KMS Default',
    'lucas-kms-default',
    '{}'::jsonb,
    'standard',
    'system',
    '{}'::jsonb,
    '{}'::jsonb
)
ON CONFLICT (id) DO NOTHING;

-- Verify
SELECT
  (SELECT count(*) FROM information_schema.columns
   WHERE table_name = 'repositories'
     AND column_name IN ('search_mode','display_config','llm_config','agent_id','namespace')
  ) AS repo_cols_added,
  (SELECT count(*) FROM information_schema.columns
   WHERE table_name = 'api_keys' AND column_name = 'created_by'
  ) AS apikey_col_added,
  (SELECT count(*) FROM tenants
   WHERE id = '00000000-0000-0000-0000-000000000001'
  ) AS default_tenant_exists;
-- Expected: repo_cols_added=5, apikey_col_added=1, default_tenant_exists=1
