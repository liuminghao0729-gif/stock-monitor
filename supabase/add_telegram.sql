-- 在 Supabase 的 SQL Editor 里整段执行一次(给「盘中每小时摘要发到自己的 Telegram」用)。
-- 只是给 user_data 表加两列;原有的自选股、持仓、行级权限(每人只能读写自己的行)都不变。
alter table public.user_data add column if not exists tg_chat_id text;                      -- 用户自己的 Telegram 聊天编号(数字)
alter table public.user_data add column if not exists tg_hourly boolean not null default true; -- 是否发盘中每小时摘要
