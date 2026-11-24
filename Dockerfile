FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# setuptools нужен для сборки из pyproject
RUN pip install --no-cache-dir "setuptools>=69"

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

COPY config ./config
COPY prompts ./prompts
COPY migrations ./migrations
COPY alembic.ini ./

COPY data ./data

# runtime/ монтируется volume-ом в docker-compose: туда пишет SQLite и досье
RUN mkdir -p /app/runtime

CMD ["python", "-m", "src.main"]