FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY mcp-server/requirements.txt /srv/mcp-server/
RUN pip install -r /srv/mcp-server/requirements.txt

COPY mcp-server /srv/mcp-server

ENV PYTHONPATH=/srv/mcp-server
WORKDIR /srv/mcp-server

EXPOSE 8765
CMD ["python", "server.py", "--transport", "http", "--host", "0.0.0.0", "--port", "8765"]
