-- Phase 0 durable queue. Apply this migration through the Supabase SQL editor
-- or the project's migration workflow before starting an executor.
create extension if not exists pgcrypto;

create table if not exists public.jobs (
    id uuid primary key default gen_random_uuid(),
    kind text not null,
    payload jsonb not null default '{}'::jsonb,
    status text not null default 'queued'
        check (status in ('queued', 'running', 'done', 'failed')),
    checkpoint jsonb not null default '{}'::jsonb,
    run_after timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists jobs_status_run_after_idx
    on public.jobs (status, run_after);

create or replace function public.set_jobs_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger jobs_set_updated_at
before update on public.jobs
for each row execute function public.set_jobs_updated_at();

-- This single RPC is the queue's atomic claim operation. SKIP LOCKED permits
-- multiple executors to claim different ready jobs without blocking each other.
create or replace function public.claim_next_job(p_kind_filter text default null)
returns setof public.jobs
language plpgsql
as $$
declare
    claimed public.jobs;
begin
    with next_job as (
        select id
        from public.jobs
        where status = 'queued'
          and run_after <= now()
          and (p_kind_filter is null or kind = p_kind_filter)
        order by run_after asc, created_at asc
        for update skip locked
        limit 1
    )
    update public.jobs as job
    set status = 'running'
    from next_job
    where job.id = next_job.id
    returning job.* into claimed;

    if found then
        return next claimed;
    end if;
end;
$$;

create or replace function public.checkpoint_job(p_job_id uuid, p_state jsonb)
returns public.jobs
language sql
as $$
    update public.jobs
    set checkpoint = coalesce(p_state, '{}'::jsonb)
    where id = p_job_id
    returning *;
$$;

create or replace function public.complete_job(p_job_id uuid)
returns public.jobs
language sql
as $$
    update public.jobs
    set status = 'done'
    where id = p_job_id
    returning *;
$$;

create or replace function public.fail_job(p_job_id uuid, p_error text)
returns public.jobs
language sql
as $$
    update public.jobs
    set status = 'failed',
        checkpoint = coalesce(checkpoint, '{}'::jsonb)
            || jsonb_build_object('error', jsonb_build_object('message', p_error))
    where id = p_job_id
    returning *;
$$;
