-- =====================================================================
-- 首次启动时自动创建业务数据库（MySQL 官方镜像 entrypoint 自动执行）
-- =====================================================================

-- 数仓库：模拟电商数据（订单/商品/用户/类目/流量）
CREATE DATABASE IF NOT EXISTS dw_ecom DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 元数据库：YAML 同步而来的表/字段/指标口径
CREATE DATABASE IF NOT EXISTS meta_db DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
