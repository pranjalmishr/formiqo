FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends chromium tesseract-ocr tesseract-ocr-eng libgomp1 fonts-dejavu-core libreoffice-writer libreoffice-impress libreoffice-calc bubblewrap && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN useradd --create-home --uid 10001 resumeai && mkdir -p /app/private-storage && chown -R resumeai:resumeai /app
COPY --chown=resumeai:resumeai app ./app
COPY --chown=resumeai:resumeai logging.json ./logging.json
USER resumeai
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)" || exit 1
# One API instance only: extraction queue and rate limiter are process-local.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--limit-concurrency", "32", "--timeout-keep-alive", "5", "--log-config", "logging.json"]
