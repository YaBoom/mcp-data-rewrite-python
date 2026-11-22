# syntax=docker/dockerfile:1
FROM python:3.13-slim

# PYTHONUNBUFFERED：stdio 服务必须关缓冲，否则日志和协议帧都可能滞留
# UV_PYTHON_DOWNLOADS=never：直接用镜像自带的 3.13，不再下载一份解释器
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON_PREFERENCE=only-system

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# ① 先只拷依赖清单，装第三方依赖。这一层能被缓存复用。
#    README.md 必须一起拷：pyproject.toml 里 readme = "README.md"
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# ② 再拷源码，安装本项目自身
COPY src ./src
RUN uv sync --frozen --no-dev

# 非 root 运行
RUN useradd --create-home --uid 10001 app \
    && chown -R app:app /app
USER app

# stdio 传输：只保 stdin/stdout，不加 TTY
ENTRYPOINT ["uv", "run", "--frozen", "--no-sync", "python", "-m", "mcp_data_rewrite_python"]
