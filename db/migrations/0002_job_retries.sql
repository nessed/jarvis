-- Queue durability: attempts/backoff/timeout/dead-letter. Additive only —
-- no existing column, row, or RPC signature is dropped or renamed. Apply
-- through the same path used for 0001_jobs.sql.

alter table public.jobs
    add column if not exists attempts int not null default 0,
    add column if not exists max_attempts int not null default 5,
    add column if not exists timeout_seconds int not null default 300;

-- Existing rows backfill to attempts=0, max_attempts=5, timeout_seconds=300
-- via the column defaults above.

alter table public.jobs drop constraint if exists jobs_status_check;
alter table public.jobs add constraint jobs_status_check
    check (status in ('queued', 'running', 'done', 'failed', 'dead_letter'));

-- Atomic claim: unchanged single-statement `for update skip locked` shape,
-- widened to also reclaim a `running` row whose lease
-- (updated_at + timeout_seconds) has expired. A row that has NOT exceeded
-- its own timeout can still only ever be claimed by one executor at a time
-- — the reclaim branch is deliberately the retry mechanism for a dead
-- executor, the same trade-off every lease-based queue makes.
create or replace function public.claim_next_job(p_kind_filter text default null)
returns setof public.jobs
language plpgsql
set search_path = ''
as $$
declare
    claimed public.jobs;
begin
    -- A stale `running` row that has already exhausted its attempts must not
    -- be reclaimed forever by a crash-looping executor; terminate it instead.
    update public.jobs
    set status = 'dead_letter',
        checkpoint = coalesce(checkpoint, '{}'::jsonb)
            || jsonb_build_object(
                'error', jsonb_build_object('message', 'exhausted after stale timeout')
            )
    where status = 'running'
      and attempts >= max_attempts
      and updated_at + make_interval(secs => timeout_seconds) < now();

    with next_job as (
        select id
        from public.jobs
        where (
                (status = 'queued' and run_after <= now())
                or (status = 'running'
                    and updated_at + make_interval(secs => timeout_seconds) < now())
              )
          and (p_kind_filter is null or kind = p_kind_filter)
        order by run_after asc, created_at asc
        for update skip locked
        limit 1
    )
    update public.jobs as job
    set status = 'running',
        attempts = job.attempts + 1
    from next_job
    where job.id = next_job.id
    returning job.* into claimed;

    if found then
        return next claimed;
    end if;
end;
$$;

-- Backoff delay is computed by the caller (unit-testable in Python); this
-- RPC just applies attempts-vs-max_attempts atomically alongside it.
create or replace function public.retry_or_dead_letter_job(
    p_job_id uuid, p_error text, p_delay_seconds int default 0
)
returns public.jobs
language plpgsql
set search_path = ''
as $$
declare
    result public.jobs;
begin
    update public.jobs
    set status = case when attempts >= max_attempts then 'dead_letter' else 'queued' end,
        run_after = case
            when attempts >= max_attempts then run_after
            else now() + make_interval(secs => greatest(0, p_delay_seconds))
        end,
        checkpoint = coalesce(checkpoint, '{}'::jsonb)
            || jsonb_build_object(
                'error', jsonb_build_object('message', p_error),
                'attempts', attempts
            )
    where id = p_job_id
    returning * into result;

    return result;
end;
$$;

create or replace function public.set_job_timeout(p_job_id uuid, p_timeout_seconds int)
returns public.jobs
language sql
set search_path = ''
as $$
    update public.jobs
    set timeout_seconds = greatest(1, p_timeout_seconds)
    where id = p_job_id
    returning *;
$$;

revoke execute on function public.retry_or_dead_letter_job(uuid, text, int)
    from public, anon, authenticated;
revoke execute on function public.set_job_timeout(uuid, int)
    from public, anon, authenticated;
grant execute on function public.retry_or_dead_letter_job(uuid, text, int) to service_role;
grant execute on function public.set_job_timeout(uuid, int) to service_role;
