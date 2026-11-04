# Reference build, not built/qualified in this release. Pin a tested digest before deployment.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt
COPY puryf ./puryf
RUN mkdir -p /var/lib/puryf/data && chown -R 10001:10001 /var/lib/puryf
USER 10001:10001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LOCALAPPDATA=/var/lib/puryf/data/runtime
CMD ["python", "-m", "puryf", "serve", "--config", "/etc/puryf/server.json"]
