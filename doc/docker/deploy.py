#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「是啊吃什么」一键部署（§12 M6）——跨平台 Python 版（Windows/Linux/macOS）。

用法:
  python doc/docker/deploy.py lite          # Lite 模式（SQLite+Kuzu+Qdrant 文件嵌入，零外部依赖）
  python doc/docker/deploy.py enterprise    # 企业级模式（PG+Milvus+Neo4j 每库一容器 + 前后端）
  python doc/docker/deploy.py status        # 查看两种模式运行状态
  python doc/docker/deploy.py down          # 停止两种模式
  python doc/docker/deploy.py --env-file path/to/.env lite   # 指定部署参数文件

首次运行自动复制 .env.example -> .env（编辑填写 DEEPSEEK_API_KEY 后重新运行）；
重复部署自动复用已有 .env（依赖层走 Docker 缓存，秒级）。
依赖: Python 3.8+ 与 docker CLI（Docker Desktop / docker engine），无需 bash。
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # doc/docker/deploy.py -> 仓库根
ENV_EXAMPLE = ROOT / "doc" / "docker" / ".env.example"
LITE_COMPOSE = ROOT / "doc" / "docker" / "lite" / "docker-compose.yml"
ENT_COMPOSE = ROOT / "doc" / "docker" / "docker-compose.yml"

PLACEHOLDER_KEY = "sk-xxxxxxxxxxxxxxxx"
KEY_RE = re.compile(r"^DEEPSEEK_API_KEY=(\S+)$")


def log(msg: str) -> None:
    print(f"[deploy] {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"[deploy] [WARN] {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def docker(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """调用 docker CLI，继承输出，Windows/Linux 通用。"""
    return subprocess.run(["docker", *args], check=check)


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env


def prepare_env(env_file: Path) -> dict[str, str]:
    """首次自动复制模板；校验 DEEPSEEK_API_KEY 已填写。返回解析后的键值。"""
    if not env_file.exists():
        shutil.copyfile(ENV_EXAMPLE, env_file)
        log(f"已生成 {env_file.relative_to(ROOT)}")
        fail("请先编辑它填入 DEEPSEEK_API_KEY（密码/端口等参数也在此），然后重新运行本命令")
    env = read_env(env_file)
    key = env.get("DEEPSEEK_API_KEY", "").strip().strip('"').strip("'")
    if not key or key == PLACEHOLDER_KEY:
        fail(f"{env_file.relative_to(ROOT)} 中 DEEPSEEK_API_KEY 未填写，请编辑后重新运行")
    return env


def compose_cmd(env_file: Path, compose: Path, *args: str) -> list[str]:
    cmd = ["compose"]
    if env_file.exists():  # status/down 时 .env 可能尚未生成，不传则用 compose 默认值
        cmd += ["--env-file", str(env_file)]
    return cmd + ["-f", str(compose), *args]


def mode_deploy(mode: str, env_file: Path) -> None:
    env = prepare_env(env_file)
    compose = LITE_COMPOSE if mode == "lite" else ENT_COMPOSE
    log(f"构建并启动（{mode} 模式）...")
    docker(compose_cmd(env_file, compose, "up", "-d", "--build"))
    port = env.get("FRONTEND_PORT", "8080").strip().strip('"')
    log(f"完成，访问 http://localhost:{port or 8080}")
    log(f"健康检查: http://localhost:{port or 8080}/api/v1/health")


def mode_status(env_file: Path) -> None:
    log("Lite 模式:")
    docker(compose_cmd(env_file, LITE_COMPOSE, "ps"), check=False)
    log("企业级模式:")
    docker(compose_cmd(env_file, ENT_COMPOSE, "ps"), check=False)


def mode_down(env_file: Path) -> None:
    docker(compose_cmd(env_file, LITE_COMPOSE, "down"), check=False)
    docker(compose_cmd(env_file, ENT_COMPOSE, "down"), check=False)
    log("已停止（两种模式）")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="「是啊吃什么」一键部署（Lite / 企业级）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "模式:\n"
            "  lite        Lite 模式（SQLite+Kuzu+Qdrant 文件嵌入，零外部依赖）\n"
            "  enterprise  企业级模式（PG+Milvus+Neo4j 每库一容器 + 前后端）\n"
            "  status      查看两种模式运行状态\n"
            "  down        停止两种模式\n"
            "示例:\n"
            "  python doc/docker/deploy.py lite\n"
            "  python doc/docker/deploy.py --env-file doc/docker/.env enterprise"
        ),
    )
    parser.add_argument("mode", choices=["lite", "enterprise", "status", "down"],
                        help="部署模式")
    parser.add_argument("--env-file", default=None,
                        help="部署参数文件（默认 doc/docker/.env）")
    args = parser.parse_args()
    env_file = Path(args.env_file) if args.env_file else ROOT / "doc" / "docker" / ".env"
    if not env_file.is_absolute():
        env_file = (ROOT / env_file).resolve()

    if args.mode == "status":
        mode_status(env_file)
    elif args.mode == "down":
        mode_down(env_file)
    else:
        mode_deploy(args.mode, env_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
