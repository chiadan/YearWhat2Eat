# 「是啊吃什么」后端镜像（§12.4 / §12 M6 部署）
# - 单 worker 进程模型（§12.4）：本地模型只加载一份
# - 依赖统一 requirements.txt（精确锁定，§16 决策 9）
# - 数据源（data/HowToCook-1.6.0）与业务数据（SQLite/Kùzu/Qdrant local 文件）经卷挂载/命名卷，
#   镜像不含数据（构建快、数据源只读原则，§12.5）
# - pip 源：清华镜像（国内构建稳）；有代理需求时构建期透传 HTTP_PROXY 亦可（不写死端口）
# - torch：默认 CPU 版（镜像小、下载稳）；GPU 服务器请删除下面 CPU 安装行，
#   改由 requirements.txt 安装默认（CUDA）版
FROM python:3.12-slim

WORKDIR /app

# 构建代理（可选）：宿主环境有 HTTP_PROXY 时 compose 自动透传（如 clash 7897），不写死端口
ARG HTTP_PROXY=
ARG HTTPS_PROXY=
ARG NO_PROXY=
ENV HTTP_PROXY=$HTTP_PROXY HTTPS_PROXY=$HTTPS_PROXY NO_PROXY=$NO_PROXY

# CPU 版 torch（GPU 服务器删除此行，requirements.txt 装 CUDA 版）
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --timeout 120 --retries 5 \
    torch==2.5.1+cpu --extra-index-url https://download.pytorch.org/whl/cpu

# pymilvus 依赖 pkg_resources（python:3.12-slim 无 setuptools；80.x 仍含 pkg_resources）
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --timeout 120 --retries 5 "setuptools<81"

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --timeout 120 --retries 5 -r requirements.txt

COPY app ./app
COPY alembic.ini .
COPY scripts ./scripts
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
