# EFPVL API image: installs the engine as a package, then the API deps.
# Build context is the repo root (see docker-compose.yml).
FROM python:3.12-slim

WORKDIR /app

COPY engine/ /tmp/engine/
RUN pip install --no-cache-dir /tmp/engine && rm -rf /tmp/engine

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY engine/efpvl_engine ./efpvl_engine
COPY api/app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
