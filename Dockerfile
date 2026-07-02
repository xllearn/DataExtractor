# syntax=docker/dockerfile:1

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements-runtime.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-runtime.txt

COPY . .

RUN mkdir -p /app/outputs /app/logs /app/uploads /app/config

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()" || exit 1

CMD ["python", "api_server.py", "--host", "0.0.0.0", "--port", "8000", "--app-config", "config/app_config.yml"]

FROM runtime AS ocr

RUN apt-get update \
    && apt-get install --no-install-recommends -y libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install paddleocr==2.10.0 paddlepaddle==2.6.2
