# ---- build stage: install dependencies into a virtualenv ----
FROM python:3.11-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements/app.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# ---- runtime stage ----
FROM python:3.11-slim
# LightGBM needs the OpenMP runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ARTIFACT_DIR=/app/artifacts \
    OMP_NUM_THREADS=1
WORKDIR /app
COPY ml/__init__.py ml/features.py ./ml/
COPY app/ ./app/
# Model artifacts are baked in, so an image tag pins exactly one model.
COPY artifacts/model.txt artifacts/metadata.json artifacts/history.npz artifacts/reference_stats.json ./artifacts/
USER 10001
EXPOSE 8000
# Container Apps probes /healthz and /readyz; no Docker HEALTHCHECK needed.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "20", "--no-access-log"]
