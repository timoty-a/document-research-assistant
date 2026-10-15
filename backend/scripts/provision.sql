-- Run interactively as the local PostgreSQL administrator. No secrets in this file.
\set ON_ERROR_STOP on

-- Inspect only the proposed names. Refuse all collisions, even partially provisioned ones.
SELECT rolname FROM pg_roles WHERE rolname IN ('dra_dev', 'dra_test');
SELECT datname, pg_get_userbyid(datdba) AS owner
FROM pg_database WHERE datname IN ('dra_dev', 'dra_test');

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname IN ('dra_dev', 'dra_test'))
       OR EXISTS (SELECT FROM pg_database WHERE datname IN ('dra_dev', 'dra_test')) THEN
        RAISE EXCEPTION 'Project names already exist. Stop and establish ownership before proceeding.';
    END IF;
END $$;

BEGIN;
CREATE ROLE dra_dev LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE dra_test LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
COMMENT ON ROLE dra_dev IS 'document-research-assistant:development';
COMMENT ON ROLE dra_test IS 'document-research-assistant:test';
COMMIT;

-- psql prompts privately; do not put passwords in SQL or command arguments.
\password dra_dev
\password dra_test

CREATE DATABASE dra_dev OWNER dra_dev ENCODING 'UTF8' TEMPLATE template0;
CREATE DATABASE dra_test OWNER dra_test ENCODING 'UTF8' TEMPLATE template0;
COMMENT ON DATABASE dra_dev IS 'document-research-assistant:development';
COMMENT ON DATABASE dra_test IS 'document-research-assistant:test';
REVOKE ALL ON DATABASE dra_dev FROM PUBLIC;
REVOKE ALL ON DATABASE dra_test FROM PUBLIC;
