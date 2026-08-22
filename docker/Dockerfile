# SimpleReconDorking v1 - container image (LOCAL CODE variant)
#
# Builds from the local checkout. To build straight from GitHub instead (no local
# code needed), use docker/Dockerfile.remote.
#
# Build (from the repository root, so the whole project is in the build context):
#   docker build -t docker/simplerecondorking -f docker/Dockerfile .
#
# Run:
#   docker run --rm docker/simplerecondorking -d 'site:target.com ext:sql'
#
# Any arguments after the image name are passed straight to `python simplerecondorking.py`.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first so this layer is cached across source changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Project source (honours .dockerignore - secrets/DBs/caches are excluded).
COPY . .

# Run as a non-root user. config/ must remain writable at runtime because the
# command log + watch scheduler are stored in config/system.db.
RUN useradd --create-home --uid 1000 recon \
    && chown -R recon:recon /app
USER recon

# `docker run ... -d 'site:target.com ext:sql'`  ->  `python simplerecondorking.py -d 'site:target.com ext:sql'`
ENTRYPOINT ["python", "simplerecondorking.py"]
CMD ["--help"]
