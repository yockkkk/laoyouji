-- 康乐 · 鉴权与家庭关系扩展列补丁（幂等）
-- 使用场景：针对在旧版本 schema.sql 下已创建 users / family_bindings 表的 Supabase 实例。
-- 执行方式：Supabase Dashboard → SQL Editor → 粘贴并运行（Run）。

-- 1. 扩充 users 表鉴权相关字段
alter table public.users
  add column if not exists username text unique,
  add column if not exists password_hash text,
  add column if not exists status text not null default 'active' check (status in ('active', 'disabled')),
  -- 子女知会的跨设备送达地址（邮件）。App 是 WebView 壳，关掉即无推送通道；
  -- 厂商离线推送要企业资质、短信要签名报备，故由 SMTP 邮件兜底。
  add column if not exists email text;

-- 2. 扩充 family_bindings 表状态与邀请流转字段
alter table public.family_bindings
  add column if not exists status text not null default 'active' check (status in ('pending', 'active', 'rejected', 'revoked', 'expired')),
  add column if not exists invited_by uuid references public.users(id),
  add column if not exists approved_at timestamptz,
  add column if not exists resolved_at timestamptz,
  add column if not exists revoked_at timestamptz;

-- 3. 确保老人-子女绑定唯一性约束
create unique index if not exists uq_family_bindings_elder_child
  on public.family_bindings (elder_id, child_id);

-- 4. 显式通知 PostgREST 刷新 Schema Cache
notify pgrst, 'reload schema';
