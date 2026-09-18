FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements-dev.txt /srv/backend/
COPY agent/requirements.txt /srv/agent/
RUN pip install -r /srv/backend/requirements-dev.txt -r /srv/agent/requirements.txt

# The api service imports `app.*` (backend) and `agent.*` (orchestrator).
COPY backend /srv/backend
COPY agent /srv/agent

ENV PYTHONPATH=/srv/backend:/srv
WORKDIR /srv/backend

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
