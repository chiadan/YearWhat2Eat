#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「是啊吃什么」数据备份（§12 M6）——跨平台 Python 版。

数据都在 docker 卷/容器数据目录中，备份 = 卷打包 / 数据库逻辑导出。
输出到 backups/ 目录，可 cron/计划任务定时（示例: 0 3 * * * cd 项目根 && python doc/docker/backup.py lite）。

用法:
  python doc/docker/backup.py lite          # Lite: 打包 backend_data 卷（sqlite+kuzu+qdrant 文件）
  python doc/docker/backup.py enterprise    # 企业级: pg_dump + neo4j 数据目录 + milvus 三卷打包

依赖: Python 3.8+ 与 docker CLI，无需 bash/grep/tar 命令（卷打包借 alpine 容器完成，Windows 通用）。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "backups"
NEO4J_DATA_DIR = ROOT / "doc" / "docker" / "neo4j" / "neo4j_data"

LITE_VOLUME = "lite_backend_data"
# 企业级卷（compose 项目前缀 docker_），找不到时自动跳过并告警
ENT_VOLUMES = ["docker_pg_data", "docker_milvus_data", "docker_minio_data",
               "docker_etcd_data", "docker_backend_data"]
KEEP_DAYS = 7


def log(msg: str) -> None:
    print(f"[backup] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[backup] [WARN] {msg}", flush=True)


def docker(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], check=check)


def ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def pack_volume(vol: str, out_name: str) -> bool:
    """用 alpine 容器把 docker 卷打包为 backups/<out_name>，返回是否成功。"""
    target = OUT / out_name
    r = subprocess.run(
        ["docker", "run", "--rm",
         "-v", f"{vol}:/data:ro",
         "-v", f"{str(OUT)}:/backup",
         "alpine", "tar", "czf", f"/backup/{out_name}", "-C", "/data", "."],
        capture_output=True, text=True)
    if r.returncode != 0:
        if target.exists():
            target.unlink()
        warn(f"{vol} 打包失败（{r.stderr.strip()[:120]}）")
        return False
    log(f"已打包 {vol} -> {out_name}")
    return True


def pack_dir(host_dir: Path, out_name: str) -> bool:
    """把主机目录（如 neo4j 数据目录）打包为 backups/<out_name>。"""
    if not host_dir.exists():
        warn(f"目录不存在，跳过: {host_dir}")
        return False
    target = OUT / out_name
    r = subprocess.run(
        ["docker", "run", "--rm",
         "-v", f"{str(host_dir)}:/data:ro",
         "-v", f"{str(OUT)}:/backup",
         "alpine", "tar", "czf", f"/backup/{out_name}", "-C", "/data", "."],
        capture_output=True, text=True)
    if r.returncode != 0:
        if target.exists():
            target.unlink()
        warn(f"{host_dir} 打包失败（{r.stderr.strip()[:120]}）")
        return False
    log(f"已打包 {host_dir} -> {out_name}")
    return True


def clean_old() -> None:
    """清理 KEEP_DAYS 天前的备份文件。"""
    now = time.time()
    for f in OUT.glob("*.tgz"):
        if now - f.stat().st_mtime > KEEP_DAYS * 86400:
            f.unlink()
            log(f"清理过期备份: {f.name}")
    for f in OUT.glob("*.dump"):
        if now - f.stat().st_mtime > KEEP_DAYS * 86400:
            f.unlink()
            log(f"清理过期备份: {f.name}")


def backup_lite() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    t = ts()
    # 卷名可能随 compose 项目名变化，动态确认
    vols = subprocess.run(["docker", "volume", "ls", "-q"], capture_output=True,
                          text=True).stdout.splitlines()
    vol = LITE_VOLUME if LITE_VOLUME in vols else next(
        (v for v in vols if v.endswith("_backend_data") and "docker_" not in v), None)
    if not vol:
        warn("未找到 Lite 数据卷（lite_backend_data），Lite 部署未运行？")
        return
    pack_volume(vol, f"lite-data-{t}.tgz")
    clean_old()
    log("恢复: docker run --rm -v lite_backend_data:/data -v "
        f"{OUT}:/backup alpine tar xzf /backup/lite-data-*.tgz -C /data")


def backup_enterprise() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    t = ts()
    # 1) PG 逻辑备份（pg_dump -> docker cp 到 backups/）
    r = docker(["exec", "yeahwhat2eat-pg", "pg_dump", "-U", "postgres",
                "-d", "yeahwhat2eat", "-F", "c", "-f", "/tmp/y2e.dump"],
               check=False)
    if r.returncode == 0:
        r2 = docker(["cp", "yeahwhat2eat-pg:/tmp/y2e.dump", str(OUT / f"pg-{t}.dump")],
                    check=False)
        if r2.returncode == 0:
            log(f"pg_dump 完成 -> pg-{t}.dump")
        else:
            warn("docker cp 失败（PG 容器未运行？）")
    else:
        warn("pg_dump 失败（PG 容器未运行？）")
    # 2) neo4j 数据目录（compose bind mount，非卷）
    pack_dir(NEO4J_DATA_DIR, f"neo4j-{t}.tgz")
    # 3) milvus 相关卷（etcd/minio/milvus + backend 数据）
    for vol in ENT_VOLUMES:
        pack_volume(vol, f"{vol.removeprefix('docker_')}-{t}.tgz")
    clean_old()
    log("恢复: docker exec -i yeahwhat2eat-pg pg_restore -U postgres -d yeahwhat2eat "
        f"< {OUT / ('pg-*.dump')}")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("lite", "enterprise"):
        print("用法: python doc/docker/backup.py {lite|enterprise}", file=sys.stderr)
        return 1
    if shutil.which("docker") is None:
        print("[backup] [WARN] 未找到 docker CLI", file=sys.stderr)
        return 1
    if sys.argv[1] == "lite":
        backup_lite()
    else:
        backup_enterprise()
    return 0


if __name__ == "__main__":
    sys.exit(main())
