# syntax=docker/dockerfile:1.7
# Многоступенчатая сборка: тяжёлые зависимости (faiss, sentence-transformers,
# pdfplumber) ставим в build-stage, в runtime копируем только нужное.

FROM python:3.13-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.8.4 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=true \
    POETRY_VIRTUALENVS_IN_PROJECT=true

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install "poetry==${POETRY_VERSION}"

WORKDIR /app

COPY pyproject.toml poetry.lock ./
RUN poetry install --only=main --no-root

COPY src ./src
COPY config.default.toml template_fixed.docx ./
RUN poetry install --only=main


# ─── Runtime ─────────────────────────────────────────────────────────────────

FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Только runtime-зависимости системного уровня. pdfplumber тянет poppler через
# python-биндинги — здесь это не нужно, но если в будущем переключишься на
# pypdfium2 — добавь libgcc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 app

WORKDIR /app
COPY --from=builder --chown=app:app /app /app

USER app

# Документы кладутся снаружи в /app/docs (см. docker-compose / volumes).
VOLUME ["/app/docs", "/home/app/.teacherfactory"]

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

CMD ["streamlit", "run", "src/teacherfactory/app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", \
     "--server.headless=true", "--browser.gatherUsageStats=false"]
