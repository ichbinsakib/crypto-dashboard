-- SCALPING section (admin-only). Same model as 'events': the row is readable only by admins and the publisher job.
-- 'scalping' is deliberately NOT added to portion_access_portion_key_check or admin_set_access, so it can never be granted to a normal user.

alter table public.notifications drop constraint notifications_portion_key_check;
alter table public.notifications add constraint notifications_portion_key_check
  check (portion_key in ('screener','bigcoins','mypicks','performance','events','scalping'));

drop policy portions_select on public.portions;
create policy portions_select on public.portions for select to authenticated using (
  public.is_publisher()
  or (key in ('events','scalping') and public.is_admin())
  or (key = '_meta' and public.has_any_portion())
  or (key not in ('events','scalping') and public.has_portion(key))
);
