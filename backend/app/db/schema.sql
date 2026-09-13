-- 康乐 · Supabase 全量 DDL
-- 使用方式：Supabase Dashboard → SQL Editor → 粘贴执行
-- 安全策略：所有表开启 RLS 且不建任何 policy（默认全拒，仅 service role 经后端访问）

create extension if not exists pgcrypto;

-- ===== 用户与家庭 =====
create table if not exists public.users (
  id uuid primary key default gen_random_uuid(),
  username text unique,
  password_hash text,
  status text not null default 'active' check (status in ('active', 'disabled')),
  role text not null check (role in ('elder','child')),
  name text not null,
  phone text,
  -- 子女知会的**跨设备**送达地址（邮件）。App 是 WebView 壳，关掉就没有推送通道，
  -- 厂商离线推送要企业资质、短信要签名报备 —— 见 providers/external/mailer.py。
  -- 留空不是错误：知会照写，只是这一封发不出去，回执里如实记着原因。
  email text,
  dialect text default 'mandarin',   -- 方言偏好：mandarin / southwestern / cantonese ...
  city text default '南京',
  created_at timestamptz default now()
);
alter table public.users enable row level security;

create table if not exists public.family_bindings (
  id uuid primary key default gen_random_uuid(),
  elder_id uuid references public.users(id) on delete cascade,
  child_id uuid references public.users(id) on delete cascade,
  relation text,
  status text not null default 'active' check (status in ('pending', 'active', 'rejected', 'revoked', 'expired')),
  invited_by uuid references public.users(id),
  approved_at timestamptz,
  resolved_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz default now(),
  unique (elder_id, child_id)
);
alter table public.family_bindings enable row level security;

-- 兼容已有表的增量补丁（应对旧库中 CREATE TABLE IF NOT EXISTS 跳过建表的问题）
alter table public.users
  add column if not exists username text unique,
  add column if not exists password_hash text,
  add column if not exists status text not null default 'active' check (status in ('active', 'disabled')),
  add column if not exists email text;

alter table public.family_bindings
  add column if not exists status text not null default 'active' check (status in ('pending', 'active', 'rejected', 'revoked', 'expired')),
  add column if not exists invited_by uuid references public.users(id),
  add column if not exists approved_at timestamptz,
  add column if not exists resolved_at timestamptz,
  add column if not exists revoked_at timestamptz;

create unique index if not exists uq_family_bindings_elder_child
  on public.family_bindings (elder_id, child_id);


-- ===== 会话（append-only 唯一事实源）=====
create table if not exists public.sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.users(id),
  title text,
  created_at timestamptz default now()
);
alter table public.sessions enable row level security;

create table if not exists public.session_events (
  id bigint generated always as identity primary key,
  session_id uuid not null,
  user_id uuid references public.users(id),
  seq bigint not null,
  type text not null,
  payload jsonb not null default '{}',
  -- 作用域三件套：agent_id 是"谁说的"（子智能体各占一个，历史按此隔离），
  -- turn_id / step_id 让"第几轮第几步干了什么"可以精确回放
  agent_id text not null default 'main',
  turn_id text,
  step_id text,
  created_at timestamptz default now()
);
alter table public.session_events enable row level security;
create index if not exists idx_session_events_session_seq
  on public.session_events (session_id, seq);
-- 同一会话内 seq 全序：内存计数器发号，这条唯一约束是它的数据库侧后盾
create unique index if not exists uq_session_events_session_seq
  on public.session_events (session_id, seq);
create index if not exists idx_session_events_scope
  on public.session_events (session_id, agent_id, seq);

-- ===== 高危确认任务 =====
create table if not exists public.confirmation_tasks (
  id uuid primary key default gen_random_uuid(),
  session_id uuid,
  elder_id uuid references public.users(id),
  child_id uuid references public.users(id),
  tool_name text not null,
  tool_args jsonb not null,            -- 挂起的调用参数原样冻结
  risk_level text not null default 'medium',
  amount numeric default 0,
  summary_for_child jsonb,             -- 子女端大白话摘要卡片
  status text not null default 'pending'
    check (status in ('pending','approved','rejected','expired','executed','failed')),
  expires_at timestamptz not null,
  resolved_at timestamptz,
  result jsonb,
  created_at timestamptz default now()
);
alter table public.confirmation_tasks enable row level security;
create index if not exists idx_confirmation_status on public.confirmation_tasks (status);

-- ===== 行程与守护 =====
create table if not exists public.trips (
  id uuid primary key default gen_random_uuid(),
  elder_id uuid references public.users(id),
  purpose text,
  plan jsonb,                          -- 《就医出行计划书》全文（可验收交付物）
  status text default 'planned'
    check (status in ('planned','ongoing','completed','aborted')),
  started_at timestamptz,
  ended_at timestamptz,
  created_at timestamptz default now()
);
alter table public.trips enable row level security;

create table if not exists public.trip_checkpoints (
  id uuid primary key default gen_random_uuid(),
  trip_id uuid references public.trips(id) on delete cascade,
  location text,
  lng numeric,
  lat numeric,
  status text check (status in ('normal','off_route','long_stay','arrived','not_moving')),
  note text,
  created_at timestamptz default now()
);
alter table public.trip_checkpoints enable row level security;

-- ===== 通知域 =====
create table if not exists public.notifications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.users(id) on delete cascade,
  elder_id uuid references public.users(id) on delete cascade,
  title text not null,
  summary text,
  type text default 'plan_created',
  is_read boolean default false,
  data jsonb default '{}',
  created_at timestamptz default now()
);
alter table public.notifications enable row level security;
create index if not exists idx_notifications_user on public.notifications (user_id, created_at desc);

-- ===== 健康域 =====
create table if not exists public.medication_plans (
  id uuid primary key default gen_random_uuid(),
  elder_id uuid references public.users(id),
  drug_name text not null,
  dose text,
  times jsonb not null default '[]',   -- ["08:00","20:00"]
  notes text,
  active boolean default true,
  created_at timestamptz default now()
);
alter table public.medication_plans enable row level security;

create table if not exists public.medication_logs (
  id uuid primary key default gen_random_uuid(),
  plan_id uuid references public.medication_plans(id) on delete cascade,
  scheduled_for date not null,
  scheduled_time text,
  taken_at timestamptz,
  status text default 'pending' check (status in ('pending','taken','missed'))
);
alter table public.medication_logs enable row level security;

create table if not exists public.health_records (
  id uuid primary key default gen_random_uuid(),
  elder_id uuid references public.users(id),
  record_type text check (record_type in ('report','appointment','scam_check','diet')),
  title text,
  content jsonb,
  plain_summary text,                  -- 大白话解读结果
  created_at timestamptz default now()
);
alter table public.health_records enable row level security;

-- ===== 康乐左翼·身体核心：健康指标 + 慢病登记 =====
-- 指标一条一行（不是一表一列）—— 血压/血糖/心率…的参考区间各不同，将来加新指标
-- 不该动表结构。血压是复合读数，收缩压/舒张压各占一列；其余指标用 value。
-- ``level`` 存下当时的**分诊档位**（保健/观察/建议就医/紧急）：它是判断结果而不是
-- 测量结果，但存起来才能回答"上周那条到底算不算异常"，不必拿今天的阈值去回溯。
create table if not exists public.health_metrics (
  id uuid primary key default gen_random_uuid(),
  elder_id uuid references public.users(id),
  metric_type text not null
    check (metric_type in ('bp','glucose','heart_rate','spo2','temperature','weight')),
  value numeric,                       -- 单值指标（血糖/心率/血氧/体温/体重）
  systolic numeric,                    -- 血压·收缩压
  diastolic numeric,                   -- 血压·舒张压
  unit text,
  measured_at timestamptz not null default now(),
  context text,                        -- 血糖的 空腹/餐后，血压的 晨起/睡前
  source text,                         -- 血压计 / 血糖仪 / 手动记录
  level text check (level in ('保健','观察','建议就医','紧急')),
  note text,
  created_at timestamptz default now()
);
alter table public.health_metrics enable row level security;
create index if not exists health_metrics_elder_time_idx
  on public.health_metrics (elder_id, metric_type, measured_at desc);

create table if not exists public.health_conditions (
  id uuid primary key default gen_random_uuid(),
  elder_id uuid references public.users(id),
  name text not null,                  -- 慢病名称，如 原发性高血压
  diagnosed_at text,                   -- 确诊时间（老人说的是"哪年"，存原话即可）
  severity text,                       -- 轻度/中度/重度
  active boolean default true,
  notes text,
  created_at timestamptz default now()
);
alter table public.health_conditions enable row level security;

-- ===== 邻里帮订单 =====
create table if not exists public.orders (
  id uuid primary key default gen_random_uuid(),
  elder_id uuid references public.users(id),
  service_type text check (service_type in ('canteen','cleaning','accompany')),
  items jsonb,
  amount numeric default 0,
  status text default 'dispatching'
    check (status in ('pending_confirm','dispatching','in_progress','done','cancelled')),
  provider_name text,
  timeline jsonb default '[]',         -- 派单进度 [{at, text}]
  created_at timestamptz default now()
);
alter table public.orders enable row level security;

-- ===== 隐私分级 + 审计 =====
create table if not exists public.privacy_permissions (
  id uuid primary key default gen_random_uuid(),
  elder_id uuid references public.users(id),
  child_id uuid references public.users(id),
  location_level text default 'realtime'
    check (location_level in ('realtime','city','off')),
  health_level text default 'summary'
    check (health_level in ('full','summary','off')),
  updated_at timestamptz default now(),
  unique (elder_id, child_id)
);
alter table public.privacy_permissions enable row level security;

create table if not exists public.audit_log (
  id bigint generated always as identity primary key,
  actor_id uuid,
  action text not null,
  target text,
  detail jsonb,
  created_at timestamptz default now()
);
alter table public.audit_log enable row level security;
