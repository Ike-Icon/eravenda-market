-- Turn on row level security for every table in the public schema.
--
-- No policies are created on purpose. With RLS on and no policy, any database
-- role other than the table owner (and superusers) can read and write nothing.
-- The app connects as the owner, so it is not affected and behaves exactly as
-- before. What this protects against is a second login to the same database,
-- for example a read-only reporting user or a leaked connection string for a
-- different role, which would otherwise get whatever rights it was granted.
--
-- It does not replace the permission checks in the API. Those still decide what
-- each signed-in user may see. It is a second lock behind them.
--
-- The loop covers tables that did not exist when this file was first written.
-- It runs at every start, so a table added later is covered on the next deploy.
-- A table the app user does not own is skipped instead of failing the deploy.
DO $$
DECLARE
    tbl record;
BEGIN
    FOR tbl IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        BEGIN
            EXECUTE 'ALTER TABLE public.' || quote_ident(tbl.tablename) || ' ENABLE ROW LEVEL SECURITY';
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE NOTICE 'Skipped row level security on a table this user does not own';
        END;
    END LOOP;
END $$;
