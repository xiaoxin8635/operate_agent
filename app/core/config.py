# -*- coding: utf-8 -*-
"""
全局配置模块

配置分层与优先级（高 → 低）：
    1. 环境变量 / .env（密钥与连接密码，双下划线嵌套，如 MYSQL__PASSWORD）
    2. config/app_settings.yaml（业务参数）
    3. 代码内默认值

用法：
    from app.core.config import get_settings
    settings = get_settings()
    settings.mysql.port
"""
from functools import lru_cache
from typing import Any

from pydantic import BaseModel
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class MySQLSettings(BaseModel):
    """MySQL 连接配置（dw 数仓库 + meta 元数据库共用实例）"""

    host: str = "127.0.0.1"
    port: int = 3307
    user: str = "root"
    password: str = ""            # 由 .env 中 MYSQL__PASSWORD 注入
    dw_database: str = "dw_ecom"
    meta_database: str = "meta_db"
    pool_size: int = 5
    pool_recycle: int = 3600

    def url_for(self, database: str) -> str:
        """构造指向指定数据库的 SQLAlchemy 连接 URL（脚本与测试使用）

        Args:
            database: 数据库名，如 dw_ecom / meta_db

        Returns:
            mysql+pymysql 连接 URL 字符串
        """
        return (
            f"mysql+pymysql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{database}?charset=utf8mb4"
        )


class QdrantSettings(BaseModel):
    """Qdrant 向量库配置"""

    url: str = "http://127.0.0.1:6333"
    field_collection: str = "field_index"
    metric_collection: str = "metric_index"


class ESSettings(BaseModel):
    """Elasticsearch 配置"""

    host: str = "http://127.0.0.1:9200"
    value_index: str = "field_value_index"
    top_values_per_field: int = 100     # 每字段高频取值聚合上限


class LLMSettings(BaseModel):
    """LLM（DeepSeek）配置"""

    base_url: str = "https://api.deepseek.com/v1"
    api_key: str = ""             # 由 .env 中 LLM__API_KEY 注入
    model: str = "deepseek-chat"
    temperature: float = 0.0
    max_tokens: int = 2048
    timeout: int = 60


class EmbeddingSettings(BaseModel):
    """BGE Embedding 模型配置"""

    model_name: str = "BAAI/bge-small-zh-v1.5"
    device: str = "cpu"
    batch_size: int = 64
    cache_dir: str = "models_cache"


class RecallSettings(BaseModel):
    """召回参数配置（向量 top-k、阈值、ES 条数）"""

    field_top_k: int = 20
    metric_top_k: int = 5
    field_score_threshold: float = 0.6
    metric_score_threshold: float = 0.6
    es_size: int = 10


class GraphSettings(BaseModel):
    """LangGraph 流水线参数（纠错轮数、SQL 约束、结果截断）"""

    max_repair_rounds: int = 3
    sql_max_limit: int = 1000
    sql_timeout_seconds: int = 10
    result_row_limit: int = 200
    enable_answer_summary: bool = True


class Settings(BaseSettings):
    """应用全局配置（聚合 YAML 业务参数与 .env 密钥）"""

    log_level: str = "INFO"       # 日志级别，由 .env 中 LOG_LEVEL 注入

    mysql: MySQLSettings = MySQLSettings()
    qdrant: QdrantSettings = QdrantSettings()
    es: ESSettings = ESSettings()
    llm: LLMSettings = LLMSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()
    recall: RecallSettings = RecallSettings()
    graph: GraphSettings = GraphSettings()

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        yaml_file="config/app_settings.yaml",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """定义配置来源优先级：初始化参数 > 环境变量 > .env > YAML"""
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


@lru_cache
def get_settings() -> Any:
    """获取全局配置单例（进程内缓存，避免重复解析配置文件）"""
    return Settings()
