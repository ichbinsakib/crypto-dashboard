-- Market Events & Economic Intelligence (admin-only). Applied to Supabase as
-- `market_events_schema` followed by `market_events_admin_only` (merged here into the final state).
-- Earlier migrations (kairo_schema_and_rls, kairo_admin_and_notify_functions) created profiles,
-- portion_access, portions, notifications and the is_admin()/is_publisher()/has_portion() helpers.

alter table public.notifications drop constraint notifications_portion_key_check;
alter table public.notifications add constraint notifications_portion_key_check
  check (portion_key in ('screener','bigcoins','mypicks','performance','events'));

-- 'events' is NOT grantable to ordinary users: only admins (public.is_admin()) can ever read it.
create or replace function public.admin_set_access(p_user uuid, p_portion text, p_granted boolean)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'not authorized' using errcode = '42501'; end if;
  if p_portion not in ('screener','bigcoins','mypicks','performance') then raise exception 'unknown portion'; end if;
  if p_granted then
    insert into public.portion_access (user_id, portion_key) values (p_user, p_portion) on conflict do nothing;
  else
    delete from public.portion_access where user_id = p_user and portion_key = p_portion;
  end if;
end $$;

create table public.economic_events (
  id text primary key,
  event_name text not null,
  event_type text not null,
  family text not null default 'OTHER',
  source text not null,
  release_datetime timestamptz not null,
  timezone text not null default 'America/New_York',
  reference_period text,
  impact_level text not null default 'LOW' check (impact_level in ('LOW','MEDIUM','HIGH','VERY_HIGH')),
  impact_score int not null default 1,
  description text,
  unit text,
  forecast numeric,
  forecast_source text,
  actual numeric,
  previous numeric,
  revision numeric,
  surprise numeric,
  surprise_classification text,
  status text not null default 'SCHEDULED' check (status in ('SCHEDULED','RELEASED','CANCELLED','ERROR')),
  market_relevance text,
  pre_event_bias text,
  post_event_assessment jsonb,
  market_reaction jsonb,
  details jsonb not null default '{}'::jsonb,
  source_url text,
  data_status text not null default 'LIVE' check (data_status in ('LIVE','RECENT','STALE','UNAVAILABLE','ERROR')),
  retrieved_at timestamptz,
  last_updated timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index economic_events_release_idx on public.economic_events (release_datetime);
create index economic_events_type_idx on public.economic_events (event_type, release_datetime);

create table public.event_market_reactions (
  id bigserial primary key,
  event_id text not null references public.economic_events(id) on delete cascade,
  asset text not null,
  price_before numeric, price_5m numeric, price_15m numeric, price_30m numeric,
  price_1h numeric, price_4h numeric, price_24h numeric,
  return_5m numeric, return_15m numeric, return_30m numeric,
  return_1h numeric, return_4h numeric, return_24h numeric,
  max_favorable_excursion numeric, max_adverse_excursion numeric,
  volatility_change numeric,
  complete boolean not null default false,
  computed_at timestamptz not null default now(),
  unique (event_id, asset)
);

create table public.fedwatch_snapshots (
  id bigserial primary key,
  meeting_date date not null,
  snapshot_datetime timestamptz not null,
  target_rate text,
  cut_probability numeric check (cut_probability between 0 and 100),
  hold_probability numeric check (hold_probability between 0 and 100),
  hike_probability numeric check (hike_probability between 0 and 100),
  distribution jsonb,
  source text not null,
  raw_data jsonb,
  entered_by uuid,
  created_at timestamptz not null default now()
);
create index fedwatch_meeting_idx on public.fedwatch_snapshots (meeting_date, snapshot_datetime desc);

create table public.fomc_meetings (
  id text primary key,
  start_date date not null,
  end_date date not null,
  decision_datetime timestamptz not null,
  has_projections boolean not null default false,
  press_conference boolean not null default true,
  statement_url text,
  minutes_url text,
  rate_lower numeric, rate_upper numeric,
  prev_rate_lower numeric, prev_rate_upper numeric,
  change_bps int,
  status text not null default 'SCHEDULED',
  source_url text,
  retrieved_at timestamptz,
  updated_at timestamptz not null default now()
);

create table public.provider_status (
  source text primary key,
  data_status text not null default 'UNAVAILABLE' check (data_status in ('LIVE','RECENT','STALE','UNAVAILABLE','ERROR')),
  retrieved_at timestamptz,
  last_updated timestamptz,
  last_attempt timestamptz,
  consecutive_failures int not null default 0,
  next_retry timestamptz,
  message text
);

create table public.event_config (
  key text primary key,
  value jsonb not null,
  updated_by uuid,
  updated_at timestamptz not null default now()
);

create table public.event_audit_log (
  id bigserial primary key,
  at timestamptz not null default now(),
  actor uuid,
  actor_email text,
  action text not null,
  detail jsonb
);

alter table public.economic_events enable row level security;
alter table public.event_market_reactions enable row level security;
alter table public.fedwatch_snapshots enable row level security;
alter table public.fomc_meetings enable row level security;
alter table public.provider_status enable row level security;
alter table public.event_config enable row level security;
alter table public.event_audit_log enable row level security;
revoke all on public.economic_events, public.event_market_reactions, public.fedwatch_snapshots, public.fomc_meetings,
  public.provider_status, public.event_config, public.event_audit_log from anon;

-- The 'events' section row is readable by admins (and the publisher job) only.
drop policy portions_select on public.portions;
create policy portions_select on public.portions for select to authenticated using (
  public.is_publisher()
  or (key = 'events' and public.is_admin())
  or (key = '_meta' and public.has_any_portion())
  or (key <> 'events' and public.has_portion(key))
);

create policy economic_events_select on public.economic_events for select to authenticated using (public.is_admin() or public.is_publisher());
create policy reactions_select on public.event_market_reactions for select to authenticated using (public.is_admin() or public.is_publisher());
create policy fedwatch_select on public.fedwatch_snapshots for select to authenticated using (public.is_admin() or public.is_publisher());
create policy fomc_select on public.fomc_meetings for select to authenticated using (public.is_admin() or public.is_publisher());
create policy provider_status_select on public.provider_status for select to authenticated using (public.is_admin() or public.is_publisher());
create policy event_config_select on public.event_config for select to authenticated using (public.is_admin() or public.is_publisher());
create policy audit_select on public.event_audit_log for select to authenticated using (public.is_admin());

-- Writes: the scheduled job (publisher) owns provider data. Admin edits (config, forecasts, manual FedWatch)
-- go through audited SECURITY DEFINER functions that re-check is_admin().
create policy economic_events_ins on public.economic_events for insert to authenticated with check (public.is_publisher());
create policy economic_events_upd on public.economic_events for update to authenticated using (public.is_publisher()) with check (public.is_publisher());
create policy reactions_ins on public.event_market_reactions for insert to authenticated with check (public.is_publisher());
create policy reactions_upd on public.event_market_reactions for update to authenticated using (public.is_publisher()) with check (public.is_publisher());
create policy fedwatch_ins on public.fedwatch_snapshots for insert to authenticated with check (public.is_publisher());
create policy fomc_ins on public.fomc_meetings for insert to authenticated with check (public.is_publisher());
create policy fomc_upd on public.fomc_meetings for update to authenticated using (public.is_publisher()) with check (public.is_publisher());
create policy provider_status_ins on public.provider_status for insert to authenticated with check (public.is_publisher());
create policy provider_status_upd on public.provider_status for update to authenticated using (public.is_publisher()) with check (public.is_publisher());

create function public.admin_set_event_config(p_key text, p_value jsonb)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'not authorized' using errcode = '42501'; end if;
  if p_key not in ('impact','thresholds','notifications','weights') then raise exception 'unknown config key'; end if;
  insert into public.event_config (key, value, updated_by, updated_at) values (p_key, p_value, auth.uid(), now())
    on conflict (key) do update set value = excluded.value, updated_by = excluded.updated_by, updated_at = now();
  insert into public.event_audit_log (actor, actor_email, action, detail)
    values (auth.uid(), (select email from public.profiles where user_id = auth.uid()), 'set_event_config', jsonb_build_object('key', p_key));
end $$;

create function public.admin_set_event_forecast(p_event text, p_value numeric)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'not authorized' using errcode = '42501'; end if;
  update public.economic_events set forecast = p_value,
      forecast_source = case when p_value is null then null else 'manual (admin)' end, updated_at = now()
    where id = p_event and status = 'SCHEDULED';
  if not found then raise exception 'event not found or already released'; end if;
  insert into public.event_audit_log (actor, actor_email, action, detail)
    values (auth.uid(), (select email from public.profiles where user_id = auth.uid()), 'set_event_forecast', jsonb_build_object('event', p_event, 'value', p_value));
end $$;

create function public.admin_add_fedwatch_snapshot(p_meeting date, p_target text, p_cut numeric, p_hold numeric, p_hike numeric, p_note text)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'not authorized' using errcode = '42501'; end if;
  if coalesce(p_cut,0) + coalesce(p_hold,0) + coalesce(p_hike,0) not between 98 and 102 then
    raise exception 'cut + hold + hike must add up to about 100';
  end if;
  insert into public.fedwatch_snapshots (meeting_date, snapshot_datetime, target_rate, cut_probability, hold_probability, hike_probability, source, raw_data, entered_by)
    values (p_meeting, now(), p_target, p_cut, p_hold, p_hike, 'manual entry (admin) from CME FedWatch', jsonb_build_object('note', p_note), auth.uid());
  insert into public.event_audit_log (actor, actor_email, action, detail)
    values (auth.uid(), (select email from public.profiles where user_id = auth.uid()), 'add_fedwatch_snapshot', jsonb_build_object('meeting', p_meeting));
end $$;

revoke execute on function public.admin_set_event_config(text, jsonb), public.admin_set_event_forecast(text, numeric),
  public.admin_add_fedwatch_snapshot(date, text, numeric, numeric, numeric, text) from public, anon, authenticated;
grant execute on function public.admin_set_event_config(text, jsonb), public.admin_set_event_forecast(text, numeric),
  public.admin_add_fedwatch_snapshot(date, text, numeric, numeric, numeric, text) to authenticated;
