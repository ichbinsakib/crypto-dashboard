-- TREND ENGINE SETTINGS: currently just a pinned-coin watchlist. Real breakouts on QNT and MOVR
-- were both confirmed (after the fact) to have satisfied every check of the 4h Trend Breakout rule,
-- but neither was ever scanned because the pool is a random rotation and neither coin's random draw
-- landed that run. Pinned coins are always checked every run regardless of the pool rotation.
-- Same shape and access pattern as scalp_settings: one row, admin-edited through an audited function.

create table public.trend_settings (
  key text primary key,
  value jsonb not null,
  updated_by uuid,
  updated_at timestamptz not null default now()
);

alter table public.trend_settings enable row level security;
revoke all on public.trend_settings from anon;

create policy trend_settings_select on public.trend_settings for select to authenticated using (public.is_admin() or public.is_publisher());
-- no insert/update policy: settings change only through admin_set_trend_config below

create or replace function public.admin_set_trend_config(p_value jsonb)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'not authorized' using errcode = '42501'; end if;
  if p_value is null or jsonb_typeof(p_value) <> 'object' then raise exception 'config must be an object'; end if;
  insert into public.trend_settings (key, value, updated_by, updated_at) values ('config', p_value, auth.uid(), now())
    on conflict (key) do update set value = excluded.value, updated_by = excluded.updated_by, updated_at = now();
  insert into public.event_audit_log (actor, actor_email, action, detail)
    values (auth.uid(), (select email from public.profiles where user_id = auth.uid()), 'set_trend_config', p_value);
end $$;

revoke all on function public.admin_set_trend_config(jsonb) from public, anon;
grant execute on function public.admin_set_trend_config(jsonb) to authenticated;
