#!/bin/sh
# 后端容器入口（§12 M6 部署）：迁移 -> 数据初始化（幂等）-> uvicorn 单 worker
set -e
echo "[entrypoint] alembic upgrade head ..."
python -m alembic upgrade head
echo "[entrypoint] init_data ..."
python scripts/init_data.py
echo "[entrypoint] start uvicorn ..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
