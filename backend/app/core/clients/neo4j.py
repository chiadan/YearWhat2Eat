"""Neo4j 图库实现（§4.1）：懒连接 driver，只提供查询/写入原语，不含业务。

实现 GraphStoreClient 接口（app/core/clients/base.py），经 build_graph_store 工厂按
settings.graph_store_provider 选择（§12 存储可替换：neo4j | ladybug | ...）。
"""
from __future__ import annotations

from typing import Any

from app.core.clients.base import GraphStoreClient
from app.core.config import Settings


class Neo4jClient(GraphStoreClient):
    def __init__(self, settings: Settings):
        self.settings = settings
        self._driver = None

    @property
    def driver(self):
        if self._driver is None:
            from neo4j import GraphDatabase

            self._driver = GraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            )
        return self._driver

    def run(self, query: str, **params: Any) -> list[dict]:
        """执行 Cypher 并返回记录列表（dict 形式）。"""
        with self.driver.session() as session:
            result = session.run(query, **params)
            return [dict(r) for r in result]

    def execute_write(self, query: str, **params: Any) -> None:
        with self.driver.session() as session:
            session.execute_write(lambda tx: tx.run(query, **params))

    def health(self) -> bool:
        try:
            self.run("RETURN 1 AS ok")
            return True
        except Exception:  # noqa: BLE001
            return False

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None
