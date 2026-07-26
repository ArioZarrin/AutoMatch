FROM node:24.11-alpine AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.13-slim AS runtime

LABEL org.opencontainers.image.title="AutoMatch" \
      org.opencontainers.image.description="Natural-language vehicle extraction and PostgreSQL catalogue matching" \
      org.opencontainers.image.source="https://github.com/ArioZarrin/AutoMatch"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STATIC_DIR=/app/static \
    APP_HOST=0.0.0.0 \
    APP_PORT=8080

WORKDIR /app

RUN groupadd --system automatch \
    && useradd --system --gid automatch --home-dir /app automatch

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && python -c "import spacy; nlp = spacy.load('en_core_web_md'); assert nlp.lang == 'en' and nlp.meta['name'] == 'core_web_md'"

COPY backend/ ./backend/
COPY --from=frontend-builder /build/frontend/.output/public/ ./static/

USER automatch
EXPOSE 8080

HEALTHCHECK --interval=20s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import json,urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3))"

CMD ["python", "-m", "backend"]
