-- 演示用初始化脚本：建表 + 种子数据
-- 表名必须与 src/mcp_data_rewrite_python/policy.py 的白名单一致：
--   admin   : *
--   manager : employees / departments / projects / sales
--   employee: 无 mysql_query 权限

-- 必须放在第一条可执行语句：官方 mysql 镜像里 LANG 为空，
-- mysql 客户端会回落到 latin1，中文种子数据会被双重编码成乱码。
SET NAMES utf8mb4;

CREATE DATABASE IF NOT EXISTS enterprise_db
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE enterprise_db;

-- ---------- 员工（含 4 个敏感字段，用于验证脱敏）----------
CREATE TABLE IF NOT EXISTS employees (
  id        INT PRIMARY KEY AUTO_INCREMENT,
  name      VARCHAR(50)  NOT NULL,
  department VARCHAR(50),
  phone     VARCHAR(20),
  id_card   VARCHAR(30),
  password  VARCHAR(100),
  salary    DECIMAL(10,2),
  hired_at  DATE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO employees (name, department, phone, id_card, password, salary, hired_at) VALUES
  ('张三', '技术部', '13800000001', '110101199001011234', 'p@ss-zhang', 25000.00, '2020-03-01'),
  ('李四', '销售部', '13800000002', '110101199202022345', 'p@ss-li',    18000.00, '2021-07-15'),
  ('王五', '技术部', '13800000003', '110101198803033456', 'p@ss-wang',   32000.00, '2019-01-10');

-- ---------- 部门 ----------
CREATE TABLE IF NOT EXISTS departments (
  id   INT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(50) NOT NULL,
  head VARCHAR(50),
  headcount INT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO departments (name, head, headcount) VALUES
  ('技术部', '王五', 12),
  ('销售部', '李四', 8);

-- ---------- 项目 ----------
CREATE TABLE IF NOT EXISTS projects (
  id     INT PRIMARY KEY AUTO_INCREMENT,
  name   VARCHAR(100) NOT NULL,
  owner  VARCHAR(50),
  status VARCHAR(20)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO projects (name, owner, status) VALUES
  ('数据中台', '张三', 'active'),
  ('CRM 重构', '李四', 'planning');

-- ---------- 销售（manager 可查，employee 不可查）----------
CREATE TABLE IF NOT EXISTS sales (
  id       INT PRIMARY KEY AUTO_INCREMENT,
  region   VARCHAR(50),
  amount   DECIMAL(12,2),
  month    VARCHAR(7)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO sales (region, amount, month) VALUES
  ('华东', 1250000.00, '2026-09'),
  ('华南', 980000.00,  '2026-09');

-- ---------- 审计日志（仅 admin 可通过通配符访问）----------
CREATE TABLE IF NOT EXISTS audit_logs (
  id      INT PRIMARY KEY AUTO_INCREMENT,
  actor   VARCHAR(50),
  action  VARCHAR(100),
  created_at DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO audit_logs (actor, action, created_at) VALUES
  ('system', 'daily-backup', '2026-10-30 02:00:00'),
  ('admin',  'grant-role',   '2026-10-31 10:15:00');
