"""Kùzu 图库实现（§12 存储可替换）：Kùzu 原生 Python API，嵌入式零部署。

选型理由：
  - **嵌入式图数据库**（单目录存储、零服务、类 SQLite）——与关系型 SQLite 理念一致
  - **Cypher 兼容**（Kùzu 支持 Cypher 子集）——现有图查询模板基本零改动
  - UWaterloo 团队维护，正式 release（0.x 稳定线），官方 Python 包 kuzu

注：langchain-kuzu 0.4.2 运行时依赖 langchain.chains（langchain 0.3 时代 API），
与本项目 langchain 1.x 不兼容（ModuleNotFoundError），故使用官方原生 API；
业务侧只依赖 GraphStoreClient 接口，未来 langchain-kuzu 适配 1.x 后可平滑替换。

切换：GRAPH_STORE_PROVIDER=kuzu + KUZU_DB_PATH（目录，如 ./data/kuzu）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.clients.base import GraphStoreClient
from app.core.config import Settings


class KuzuGraphStore(GraphStoreClient):
    def __init__(self, settings: Settings):
        self.settings = settings
        self._db = None
        self._conn = None

    @property
    def conn(self):
        """Kùzu 连接（懒加载：Database -> Connection，嵌入式单目录）。"""
        if self._conn is None:
            import kuzu

            db_path = self.settings.kuzu_db_path
            if db_path:
                Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
            self._db = kuzu.Database(db_path)
            self._conn = kuzu.Connection(self._db)
        return self._conn

    def run(self, query: str, **params: Any) -> list[dict]:
        """执行 Cypher 模板（参数填充，§6.5）并返回记录列表。"""
        result = self.conn.execute(query, params or None)
        # QueryResult -> list[dict]（pandas 由 torch 依赖提供）
        return result.get_as_df().to_dict("records")

    def execute_write(self, query: str, **params: Any) -> None:
        self.conn.execute(query, params or None)

    def health(self) -> bool:
        try:
            self.run("RETURN 1 AS ok")
            return True
        except Exception:  # noqa: BLE001
            return False

    def close(self) -> None:
        if self._db is not None:
            try:
                self._db.close()
            except Exception:  # noqa: BLE001
                pass
        self._db = None
        self._conn = None
