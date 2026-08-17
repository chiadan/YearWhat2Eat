#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「是啊吃什么」发布打包（§12 M6）——跨平台 Python 版。

构建镜像 -> docker save 导出为单文件 tar.gz（镜像 = Python 的"jar 包"），
目标服务器可完全离线部署（零网络依赖）。

用法:
  python doc/docker/build_release.py lite          # 构建并导出 Lite 镜像包（backend+frontend）
  python doc/docker/build_release.py enterprise    # 构建并导出企业级前后端镜像包（数据库镜像由服务器/registry 拉取）
  python doc/docker/build_release.py load <file>   # 服务器侧：docker load 导入镜像包

产物: releases/yeahwhat2eat-{mode}-{时间戳}.tar.gz —— 拷贝到目标服务器即可离线部署。
依赖: Python 3.8+ 与 docker CLI，无需 bash/gzip 命令（压缩由 Python gzip 完成）。
"""

from __future__ import annotations

import argparse
import gzip
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASES = ROOT / "releases"
LITE_COMPOSE = ROOT / "doc" / "docker" / "lite" / "docker-compose.yml"
ENT_COMPOSE = ROOT / "doc" / "docker" / "docker-compose.yml"

LITE_IMAGES = ["lite-backend:latest", "lite-frontend:latest"]
ENT_IMAGES = ["backend:latest", "frontend:latest"]


def log(msg: str) -> None:
    print(f"[release] {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"[release] [WARN] {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def docker(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], check=check)


def docker_save_gzip(images: list[str], out: Path) -> None:
    """docker save | gzip 流式写入，避免整包占内存；Windows/Linux 通用。"""
    proc = subprocess.Popen(["docker", "save", *images], stdout=subprocess.PIPE)
    assert proc.stdout is not None
    with gzip.open(out, "wb") as f:
        shutil.copyfileobj(proc.stdout, f, length=1024 * 1024)
    rc = proc.wait()
    if rc != 0:
        out.unlink(missing_ok=True)
        fail(f"docker save 失败（exit {rc}）")


def cmd_load(file: str) -> None:
    p = Path(file)
    if not p.exists():
        fail(f"镜像包不存在: {file}")
    log(f"导入镜像包: {file}")
    docker(["load", "-i", str(p)])
    log("完成，随后执行: python doc/docker/deploy.py lite (或 enterprise)")


def cmd_build(mode: str) -> None:
    RELEASES.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    if mode == "lite":
        log("构建 Lite 镜像（依赖走 Docker 层缓存，代码改动不重装依赖）...")
        docker(["compose", "-f", str(LITE_COMPOSE), "build"], check=False)
        images, tag = LITE_IMAGES, "lite"
    else:
        log("构建企业级前后端镜像（数据库镜像由服务器自行拉取/registry 提供）...")
        docker(["compose", "-f", str(ENT_COMPOSE), "build", "backend", "frontend"], check=False)
        images, tag = ENT_IMAGES, "enterprise"
    out = RELEASES / f"yeahwhat2eat-{tag}-{ts}.tar.gz"
    log(f"导出镜像 -> {out.name}")
    docker_save_gzip(images, out)
    log("部署步骤（目标服务器，可离线）:")
    log(f"  1. scp {out} user@server:/opt/yeahwhat2eat/")
    log(f"  2. ssh server 'cd /opt/yeahwhat2eat && python doc/docker/build_release.py load {out.name}'")
    log("  3. 配置 .env（DEEPSEEK_API_KEY/密码等）后 python doc/docker/deploy.py lite")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="「是啊吃什么」发布打包：构建 + docker save 导出（可离线部署）")
    parser.add_argument("mode", choices=["lite", "enterprise", "load"],
                        help="lite/enterprise=构建导出；load=服务器侧导入镜像包")
    parser.add_argument("file", nargs="?", help="load 模式下的镜像包路径")
    args = parser.parse_args()
    if args.mode == "load":
        if not args.file:
            fail("用法: python doc/docker/build_release.py load <镜像包.tar.gz>")
        cmd_load(args.file)
    else:
        cmd_build(args.mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
