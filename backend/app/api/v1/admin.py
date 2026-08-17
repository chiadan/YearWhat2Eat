"""admin 接口（§9）：ETL 触发与状态查询（admin 角色，M1 用 token 校验）。

- POST /admin/ingest：互斥检查 + 建 run 记录 -> 后台任务执行 -> 202 {run_id}
- GET  /admin/ingest/{run_id}：管道状态与日志
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.api.deps import get_settings_dep, require_admin
from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import IngestRun
from app.db.session import get_engine, get_session
from app.pipeline.runner import run_ingest

router = APIRouter(dependencies=[Depends(require_admin)])


def _create_run_or_409(session: Session) -> IngestRun:
    active = session.exec(select(IngestRun).where(IngestRun.status == "running")).first()
    if active:
        raise ConflictError("已有 ETL 管道正在运行，请等待完成（§5 ingest 并发互斥）")
    run = IngestRun(status="running", log="")
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


@router.post("/ingest", status_code=202)
async def start_ingest(
    reset: bool = True,
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    with Session(get_engine()) as session:
        run = _create_run_or_409(session)
        run_id = run.id

    # 后台执行（单 worker 进程内任务，§12.4）
    asyncio.create_task(run_ingest(settings, reset=reset, run_id=run_id))
    return {"run_id": run_id, "status": "running"}


@router.get("/ingest/{run_id}")
def get_ingest(run_id: int, session: Session = Depends(get_session)) -> dict:
    run = session.get(IngestRun, run_id)
    if run is None:
        raise NotFoundError(f"ingest run {run_id} 不存在")
    return {
        "run_id": run.id,
        "status": run.status,
        "dish_count": run.dish_count,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "log": run.log,
    }
