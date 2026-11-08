-- 在 Supabase 的 SQL Editor 里整段执行一次。每个登录用户只能读写自己的那一行。
create table if not exists public.user_data (
  user_id uuid primary key references auth.users(id) on delete cascade,
  watch jsonb not null default '[]'::jsonb,        -- 自选股代码列表
  holdings jsonb not null default '[]'::jsonb,     -- 持仓记录(下一阶段使用)
  updated_at timestamptz not null default now()
);

alter table public.user_data enable row level security;

drop policy if exists "own select" on public.user_data;
drop policy if exists "own insert" on public.user_data;
drop policy if exists "own update" on public.user_data;

create policy "own select" on public.user_data for select using (auth.uid() = user_id);
create policy "own insert" on public.user_data for insert with check (auth.uid() = user_id);
create policy "own update" on public.user_data for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
