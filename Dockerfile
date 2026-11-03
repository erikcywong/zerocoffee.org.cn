FROM python:3.12-slim

WORKDIR /app
COPY server/ ./server/
COPY . .

ENV ZV_HOST=0.0.0.0 \
    ZV_PORT=8099 \
    PYTHONUNBUFFERED=1

EXPOSE 8099
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8099/api/health',timeout=4).status==200 else 1)"

CMD ["python", "server/app.py"]
