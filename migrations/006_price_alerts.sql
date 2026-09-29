-- PRICE ALERTS: moves data/alerts_config.json into Supabase so alerts can be managed from an admin
-- panel instead of editing a JSON file through GitHub's web UI. The rules themselves are readable
-- only by the publisher job (which evaluates them) and admins (who edit them); every other user
-- only ever sees the already-evaluated results baked into the rendered dashboard page, exactly like
-- the scalp_signals / event tables never need to be read directly by an ordinary user's browser.
-- Trigger STATE (has this alert fired before, when) stays in app_state as it already did -- this
-- table is only the rule definitions.

create table public.price_alerts (
  id text primary key,
  coin text not null,
  condition text not null check (condition in ('above', 'below')),
  price numeric not null,
  label text not null,
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  updated_by uuid
);

alter table public.price_alerts enable row level security;
revoke all on public.price_alerts from anon;

create policy price_alerts_select on public.price_alerts for select to authenticated using (public.is_admin() or public.is_publisher());
-- the publisher may seed starter alerts on a first run with none configured yet (dashboard.py only
-- ever does this when the table is empty); every other write goes through the audited functions below
create policy price_alerts_ins_publisher on public.price_alerts for insert to authenticated with check (public.is_publisher());

create or replace function public.admin_upsert_price_alert(p_id text, p_coin text, p_condition text, p_price numeric, p_label text, p_enabled boolean)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'not authorized' using errcode = '42501'; end if;
  if p_condition not in ('above', 'below') then raise exception 'condition must be above or below'; end if;
  insert into public.price_alerts (id, coin, condition, price, label, enabled, updated_by, updated_at)
    values (p_id, p_coin, p_condition, p_price, p_label, p_enabled, auth.uid(), now())
    on conflict (id) do update set coin = excluded.coin, condition = excluded.condition, price = excluded.price,
      label = excluded.label, enabled = excluded.enabled, updated_by = excluded.updated_by, updated_at = now();
  insert into public.event_audit_log (actor, actor_email, action, detail)
    values (auth.uid(), (select email from public.profiles where user_id = auth.uid()), 'upsert_price_alert',
      jsonb_build_object('id', p_id, 'coin', p_coin, 'condition', p_condition, 'price', p_price, 'enabled', p_enabled));
end $$;

create or replace function public.admin_delete_price_alert(p_id text)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'not authorized' using errcode = '42501'; end if;
  delete from public.price_alerts where id = p_id;
  insert into public.event_audit_log (actor, actor_email, action, detail)
    values (auth.uid(), (select email from public.profiles where user_id = auth.uid()), 'delete_price_alert', jsonb_build_object('id', p_id));
end $$;

revoke all on function public.admin_upsert_price_alert(text, text, text, numeric, text, boolean), public.admin_delete_price_alert(text) from public, anon;
grant execute on function public.admin_upsert_price_alert(text, text, text, numeric, text, boolean), public.admin_delete_price_alert(text) to authenticated;
