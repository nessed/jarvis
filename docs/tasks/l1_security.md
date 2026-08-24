# L1 remediation — secure Supabase queue schema

## Ownership

You may edit only `db/` and `tests/db/`. Do not commit. Do not edit
`docs/context.md`; report findings and changes to the orchestrator. Do not
reveal configuration values.

## Trigger

The live project lacks `public.jobs` (`PGRST205`). The existing migration is
unsafe because it creates that exposed table with RLS disabled while the
configured application key is publishable.

## Objective

Redesign the queue persistence so it is safe before deployment:

1. Review the existing migration and jobs client.
2. Ensure the application requires a server-only Supabase secret/service-role
   key for bus/executor queue access; a publishable key must not be accepted for
   queue writes.
3. Enable RLS for an exposed table and create no public policies. Prefer the
   smallest correct change compatible with the existing client and atomic claim
   functions.
4. Update focused tests under `tests/db/` for missing/wrong key configuration
   and migration-security expectations.
5. Do not apply any live database change. Report the exact one user dashboard
   action required to create/provide the server-only key and the safest
   application path once it exists.

Use current official Supabase documentation. Do not edit requirements or any
other paths.
