-- 002_pgmq_schema_grants.sql
-- Grants service_role access to pgmq schema
BEGIN;

GRANT USAGE ON SCHEMA pgmq TO service_role;
GRANT ALL ON ALL TABLES IN SCHEMA pgmq TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA pgmq TO service_role;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA pgmq TO service_role;

COMMIT;
