# -*- coding: utf-8 -*-
"""
Meta 元数据库 ORM 模型

对应 meta_db 库四张表：
    - meta_tables   表元数据（表名/别名/描述/数仓分层）
    - meta_fields   字段元数据（别名/描述/类型/样例/是否全文索引）
    - meta_metrics  指标口径（公式/别名/关联表与字段）
    - meta_sync_log 元数据同步日志

注意：列名避免使用 MySQL 保留字（如 desc），统一用 *_desc 后缀。
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class MetaBase(DeclarativeBase):
    """Meta 元数据库 ORM 基类"""


class MetaTable(MetaBase):
    """表元数据：一张数仓表一行记录"""

    __tablename__ = "meta_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_name: Mapped[str] = mapped_column(String(64), unique=True, comment="物理表名")
    alias: Mapped[str] = mapped_column(String(128), comment="中文别名")
    table_desc: Mapped[str] = mapped_column(String(512), comment="表描述")
    layer: Mapped[str] = mapped_column(String(16), comment="数仓分层: ods/dw/dm")
    owner: Mapped[Optional[str]] = mapped_column(String(64), comment="负责人")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )


class MetaField(MetaBase):
    """字段元数据：属于某张表，一行一个字段"""

    __tablename__ = "meta_fields"
    __table_args__ = (
        # 同一表内字段名唯一，支撑 (table_id, field_name) 幂等 upsert
        UniqueConstraint("table_id", "field_name", name="uk_table_field"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meta_tables.id"), comment="所属表 ID"
    )
    field_name: Mapped[str] = mapped_column(String(64), comment="物理字段名")
    field_alias: Mapped[str] = mapped_column(String(128), comment="字段中文别名")
    field_desc: Mapped[str] = mapped_column(String(512), comment="字段描述")
    field_type: Mapped[str] = mapped_column(String(32), comment="字段类型")
    examples: Mapped[Optional[Any]] = mapped_column(JSON, comment="样例取值列表")
    searchable: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否参与取值全文索引（品牌/城市等枚举字段为 true）"
    )


class MetaMetric(MetaBase):
    """指标口径：统一业务指标定义，消除口径歧义"""

    __tablename__ = "meta_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric_name: Mapped[str] = mapped_column(String(64), unique=True, comment="指标英文标识")
    alias: Mapped[Any] = mapped_column(JSON, comment="中文别名列表（召回时用于向量文本拼接）")
    metric_desc: Mapped[str] = mapped_column(String(512), comment="指标描述与口径说明")
    formula: Mapped[str] = mapped_column(String(512), comment="计算公式")
    table_name: Mapped[str] = mapped_column(String(64), comment="主表")
    related_fields: Mapped[Any] = mapped_column(JSON, comment="关联字段列表")


class MetaSyncLog(MetaBase):
    """元数据同步日志：一次 sync_meta 执行一个批次"""

    __tablename__ = "meta_sync_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_no: Mapped[str] = mapped_column(String(32), comment="批次号（时间戳+随机）")
    yaml_file: Mapped[str] = mapped_column(String(128), comment="来源 YAML 文件名")
    status: Mapped[str] = mapped_column(String(16), comment="结果状态: success/failed")
    message: Mapped[str] = mapped_column(String(1024), comment="结果详情（含报错信息）")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )
