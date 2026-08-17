"""健康检查（§9）：逐存储探活（字段名随 provider 通用化，§12 存储可替换）；
ingest_running 供重建窗口降级判断（§5）。"""
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.api.deps import get_settings_dep
from app.core.clients.factory import build_graph_store, build_vector_store
from app.core.config import Settings
from app.db.models import IngestRun
from app.db.session import get_session

router = APIRouter()


@router.get("/health")
def health(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    """探活三存储。字段：relational（sqlite/pg）、vector（qdrant/milvus）、graph（neo4j/kuzu）。"""
    relational_ok = True
    try:
        session.exec(select(IngestRun).limit(1))
    except Exception:  # noqa: BLE001
        relational_ok = False

    graph = build_graph_store(settings)
    vector = build_vector_store(settings)
    try:
        graph_ok = graph.health()
        vector_ok = vector.health()
    finally:
        graph.close()

    running = session.exec(select(IngestRun).where(IngestRun.status == "running")).first()
    return {
        "status": "ok" if (relational_ok and graph_ok and vector_ok) else "degraded",
        "relational": relational_ok,          # sqlite | postgresql（DATABASE_URL）
        "vector": vector_ok,                  # qdrant | milvus（VECTOR_STORE_PROVIDER）
        "graph": graph_ok,                    # neo4j | kuzu（GRAPH_STORE_PROVIDER）
        "ingest_running": running is not None,
    }
