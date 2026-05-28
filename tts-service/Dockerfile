FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps — CPU-only build (no GPU needed)
RUN pip install --no-cache-dir \
    vieneu \
    fastapi \
    "uvicorn[standard]" \
    --extra-index-url https://pnnbao97.github.io/llama-cpp-python-v0.3.16/cpu/

COPY server.py .

# Pre-download model at build time (avoid runtime download)
RUN python -c "from vieneu import Vieneu; tts = Vieneu(); print('✅ VieNeu-TTS model downloaded')"

EXPOSE 23333

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:23333/health || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "23333", "--workers", "1"]
