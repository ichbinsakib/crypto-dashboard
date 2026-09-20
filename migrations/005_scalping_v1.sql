-- SCALPING V1: signal lifecycle history + engine settings. Admin-only, like 'events'.
--   * scalp_signals  one row per signal for its whole life (never deleted: no delete policy exists)
--   * scalp_settings engine settings (row 'config'); only admins can change them, through an audited function
-- The scheduled scalping job (publisher account) creates and updates signal rows; admins can only read them and
-- ask for a manual close through admin_request_scalp_close (the job carries it out at the next run).

create table public.scalp_signals (
  id text primary key,
  coin text not null,
  direction text not null check (direction in ('LONG','SHORT')),
  state text not null check (state in ('SETUP','ACTIVE','TP1_HIT','TP2_HIT','STOP_LOSS','EXPIRED','INVALIDATED','CLOSED')),
  setup_type text not null,
  timeframe text not null,
  htf text,
  regime text,
  setup_score numeric,
  quality text,
  created_at timestamptz not null,
  expires_at timestamptz not null,
  level numeric,
  entry_low numeric not null,
  entry_high numeric not null,
  stop numeric not null,
  tp1 numeric not null,
  tp2 numeric not null,
  rr numeric,
  atr numeric,
  actual_entry numeric,
  entry_time timestamptz,
  tp1_time timestamptz,
  exit_price numeric,
  exit_time timestamptz,
  exit_reason text,
  pnl_pct numeric,
  r_multiple numeric,
  mfe_pct numeric,
  mae_pct numeric,
  duration_min numeric,
  last_price numeric,
  checks jsonb not null default '[]'::jsonb,
  reason text,
  timeline jsonb not null default '[]'::jsonb,
  manual_close_requested boolean not null default false,
  updated_at timestamptz not null default now()
);
create index scalp_signals_coin_idx on public.scalp_signals (coin, created_at desc);
create index scalp_signals_state_idx on public.scalp_signals (state);

create table public.scalp_settings (
  key text primary key,
  value jsonb not null,
  updated_by uuid,
  updated_at timestamptz not null default now()
);

alter table public.scalp_signals enable row level security;
alter table public.scalp_settings enable row level security;
revoke all on public.scalp_signals, public.scalp_settings from anon;

create policy scalp_signals_select on public.scalp_signals for select to authenticated using (public.is_admin() or public.is_publisher());
create policy scalp_signals_ins on public.scalp_signals for insert to authenticated with check (public.is_publisher());
create policy scalp_signals_upd on public.scalp_signals for update to authenticated using (public.is_publisher()) with check (public.is_publisher());
-- deliberately no delete policy: a signal is never removed, whatever its outcome

create policy scalp_settings_select on public.scalp_settings for select to authenticated using (public.is_admin() or public.is_publisher());
-- no insert/update policy: settings change only through admin_set_scalp_config below

create or replace function public.admin_set_scalp_config(p_value jsonb)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'not authorized' using errcode = '42501'; end if;
  if p_value is null or jsonb_typeof(p_value) <> 'object' then raise exception 'config must be an object'; end if;
  insert into public.scalp_settings (key, value, updated_by, updated_at) values ('config', p_value, auth.uid(), now())
    on conflict (key) do update set value = excluded.value, updated_by = excluded.updated_by, updated_at = now();
  insert into public.event_audit_log (actor, actor_email, action, detail)
    values (auth.uid(), (select email from public.profiles where user_id = auth.uid()), 'set_scalp_config', jsonb_build_object('keys', (select jsonb_agg(k) from jsonb_object_keys(p_value) k)));
end $$;

create or replace function public.admin_request_scalp_close(p_id text)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'not authorized' using errcode = '42501'; end if;
  update public.scalp_signals set manual_close_requested = true, updated_at = now()
    where id = p_id and state in ('SETUP','ACTIVE','TP1_HIT');
  insert into public.event_audit_log (actor, actor_email, action, detail)
    values (auth.uid(), (select email from public.profiles where user_id = auth.uid()), 'request_scalp_close', jsonb_build_object('id', p_id));
end $$;

revoke all on function public.admin_set_scalp_config(jsonb), public.admin_request_scalp_close(text) from public, anon;
grant execute on function public.admin_set_scalp_config(jsonb), public.admin_request_scalp_close(text) to authenticated;
