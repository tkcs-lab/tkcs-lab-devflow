FROM python:3.13-slim
RUN useradd --system --uid 10001 --no-create-home board && mkdir /data && chown board /data
WORKDIR /app
COPY scripts/board_server.py scripts/board_store.py scripts/board_mcp.py scripts/build_board.py scripts/validate_status_record.py /app/scripts/
COPY board/board.html board/rules.js /app/board/
ENV DEVFLOW_BOARD_DB=/data/board.sqlite3 PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8787
USER board
HEALTHCHECK --interval=30s --timeout=5s CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=4).status == 200 else 1)"]
CMD ["python", "/app/scripts/board_server.py", "--host", "0.0.0.0", "--port", "8787"]
