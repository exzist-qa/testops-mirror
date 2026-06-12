FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

RUN pip install --no-cache-dir build && \
    python -m build --wheel --outdir /dist

# ---------------------------------------------------------------------------

FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

RUN useradd -r -s /bin/false testops-mirror

COPY --from=builder /dist/*.whl /tmp/

RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

RUN git config --system user.name "testops-mirror" && \
    git config --system user.email "testops-mirror@localhost" && \
    git config --system safe.directory "*"

USER testops-mirror

ENTRYPOINT ["testops-mirror"]
