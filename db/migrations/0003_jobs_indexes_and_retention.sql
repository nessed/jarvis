-- Indexes for the queries this repo actually issues, and a retention helper
-- that is never called on its own. Additive only: nothing is dropped,
-- renamed, or deleted, and no row is touched.
--
-- Approved by Ali on 1 September 2026 (QUESTIONS.md Q9) as the
-- "retention/index pass". Applied through db/migrate.py, which records it in
-- public.schema_migrations -- the ledger that did not exist when 0002 sat
-- unapplied for days and stranded four inbound messages.
--
-- Every index below is justified against a real query in this tree. An index
-- that cannot name its query is a write cost with no reader, and this table
-- is written on every claim, checkpoint, and completion.

-- 1. claim_next_job with a kind filter.
--
--    executor/poller.py's three workers all pass --kind, and since 2 Sep 2026
--    action-worker passes four of them, so the filtered claim runs several
--    times per poll cycle per worker. 0001's jobs_status_run_after_idx leads
--    on (status, run_after) and cannot narrow by kind, so every filtered
--    claim scans all ready rows of that status and discards the ones for
--    other kinds. Leading with (status, kind) and keeping run_after as the
--    third column serves both the equality filters and the ordering.
create index if not exists jobs_status_kind_run_after_idx
    on public.jobs (status, kind, run_after);

-- 2. The stale-lease reclaim branch.
--
--    0002 widened claim_next_job to also take a `running` row whose lease
--    (updated_at + timeout_seconds) has expired. That predicate is on
--    updated_at, which nothing indexes, so the reclaim check scans every
--    running row. Partial, because reclaim only ever looks at 'running' --
--    a full index here would be paid for on every done row for no reader.
create index if not exists jobs_running_lease_idx
    on public.jobs (updated_at)
    where status = 'running';

-- 3. /status's last_job.
--
--    bus/status.py: `select ... order by created_at desc limit 1`. Without a
--    descending index this sorts the whole table to return one row, on an
--    endpoint meant to be cheap enough to poll.
create index if not exists jobs_created_at_desc_idx
    on public.jobs (created_at desc);

-- 4. /status's distill_chain_health.
--
--    bus/status.py issues three counts filtered by kind = 'distill_memory'
--    (alive / dead-lettered / total). Index 1 above leads on status, which
--    the "total" count does not filter by, so this one leads on kind.
create index if not exists jobs_kind_status_idx
    on public.jobs (kind, status);

-- Retention.
--
-- Deliberately a function that must be called by hand, not a trigger, not a
-- scheduled job, and not a DELETE in this migration.
--
-- Every finished row is evidence. `docs/state.md` and several task logs cite
-- specific job ids as proof that something ran; a retention pass that fired
-- on its own would quietly delete the evidence behind claims this project
-- makes about itself. The same reasoning is why the orphaned
-- `queue-durability-probe-` row is reported and left in place rather than
-- swept "while we're in there" (Q9's carve-out).
--
-- So: the mechanism exists, the policy does not. Someone runs it, names a
-- cutoff, and sees the count first via the dry-run branch.
create or replace function public.prune_finished_jobs(
    p_older_than interval default interval '90 days',
    p_dry_run boolean default true
)
returns table (kind text, status text, row_count bigint)
language plpgsql
as $$
begin
    if p_dry_run then
        return query
            select j.kind, j.status, count(*)::bigint
            from public.jobs j
            where j.status in ('done', 'dead_letter')
              and j.updated_at < now() - p_older_than
            group by j.kind, j.status;
    else
        return query
            with deleted as (
                delete from public.jobs j
                where j.status in ('done', 'dead_letter')
                  and j.updated_at < now() - p_older_than
                returning j.kind, j.status
            )
            select d.kind, d.status, count(*)::bigint
            from deleted d
            group by d.kind, d.status;
    end if;
end;
$$;

-- Same grant shape as 0001: server-only, never the anon or authenticated role.
revoke execute on function public.prune_finished_jobs(interval, boolean) from public, anon, authenticated;
grant execute on function public.prune_finished_jobs(interval, boolean) to service_role;
