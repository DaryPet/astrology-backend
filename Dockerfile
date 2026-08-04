# Base image matches the Python the project is developed and tested on
# (local venv: 3.9.6), so runtime behaviour on the server matches what works.
FROM python:3.9-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.hf_cache

WORKDIR /app

COPY requirements.txt .

# Single layer on purpose: install compilers (pyswisseph / numpy need them when
# no prebuilt wheel exists for the platform), build the dependencies, then drop
# the compilers again. Left in place they add hundreds of MB to an image that
# gets pulled on every cold start.
#
# torch is installed SEPARATELY from the CPU wheel index: the default wheel
# drags in CUDA (~2 GB), and Cloud Run has no GPU.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Bake the embedding model into the image at build time. Without this the first
# request after every cold start would download ~500 MB from HuggingFace: slow,
# and dependent on a third party being up.
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"

# Set only AFTER the download above, otherwise that step has nothing to fetch.
# Without this flag sentence-transformers still calls huggingface.co on every
# start to check for updates: it adds latency to each cold start and makes the
# service fail outright when HuggingFace is unreachable (verified: the container
# crashes with --network none unless this is set). With it the model loads from
# the image in ~3s instead of ~10s.
ENV HF_HUB_OFFLINE=1

# Cloud Run passes the port in $PORT and does not guarantee 8080.
# exec keeps uvicorn as PID 1 so it receives the shutdown signal.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
