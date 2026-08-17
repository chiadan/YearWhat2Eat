"""存储抽象层（§4/§7 可替换存储）：向量库与图库的统一接口。

设计目标：SQLite/PG 等关系型由 SQLAlchemy ORM 天然抽象（database_url 切换）；
向量库 / 图库通过本模块接口 + factory 实现可插拔——
  向量：QdrantClient（默认）/ MilvusVectorStore / 其他（继承 VectorStoreClient）
  图：  Neo4jClient（默认）/ LadybugGraphStore / 其他（继承 GraphStoreClient）
新数据库接入 = 继承对应接口实现方法 + 在 factory 注册 provider 名（文档见 §12 存储可替换）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class VectorStoreClient(ABC):
    """向量数据库接口：集合管理 + 写入 + 检索原语（与具体实现解耦）。"""

    @abstractmethod
    def ensure_collection(
        self,
        name: str,
        *,
        vector_size: int,
        payload_indexes: list[tuple[str, str]] | None = None,
    ) -> None:
        """确保集合存在（不存在则创建，含向量维度与 payload 索引）。"""

    @abstractmethod
    def upsert_points(self, collection: str, points: list[dict], batch_size: int = 500) -> None:
        """写入/更新向量：points = [{id, vector, payload}]。"""

    @abstractmethod
    def search(
        self,
        collection: str,
        vector: list[float],
        *,
        top_k: int = 10,
        score_threshold: float | None = None,
        payload_filter: dict | None = None,
    ) -> list[dict]:
        """余弦相似度检索：返回 [{id, score, payload}]。"""

    @abstractmethod
    def scroll(
        self,
        collection: str,
        *,
        payload_filter: dict | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """按 payload 过滤遍历（诊断/调试用）。"""

    @abstractmethod
    def count(self, collection: str) -> int:
        """集合点数。"""

    @abstractmethod
    def collection_exists(self, name: str) -> bool:
        """集合是否存在。"""

    @abstractmethod
    def delete_collection(self, name: str) -> None:
        """删除集合（ETL 重建用）。"""

    @abstractmethod
    def health(self) -> bool:
        """连通性检查。"""


class GraphStoreClient(ABC):
    """图数据库接口：预置模板查询 + 写入原语（不含业务，§6.5 Cypher 不自由生成）。"""

    @abstractmethod
    def run(self, query: str, **params: Any) -> list[dict]:
        """执行查询模板（参数填充），返回记录列表。"""

    @abstractmethod
    def execute_write(self, query: str, **params: Any) -> None:
        """执行写事务（ETL 写入 / 行为回写）。"""

    @abstractmethod
    def health(self) -> bool:
        """连通性检查。"""

    @abstractmethod
    def close(self) -> None:
        """释放连接资源。"""
