# Build from the repository root: docker build -f deploy/board/Dockerfile -t tld-board .
FROM python:3.13-slim
RUN useradd --system --uid 10001 --no-create-home board && mkdir /data && chown board /data
WORKDIR /app
COPY src/tld/__init__.py /app/src/tld/
COPY src/tld/board/__init__.py src/tld/board/server.py src/tld/board/store.py src/tld/board/mcp.py src/tld/board/build.py src/tld/board/record.py /app/src/tld/board/
COPY src/tld/board/web/board.html src/tld/board/web/rules.js /app/src/tld/board/web/
ENV TLD_BOARD_DB=/data/board.sqlite3 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
VOLUME ["/data"]
EXPOSE 8787
USER board
HEALTHCHECK --interval=30s --timeout=5s CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=4).status == 200 else 1)"]
CMD ["python", "-m", "tld.board.server", "--host", "0.0.0.0", "--port", "8787"]
