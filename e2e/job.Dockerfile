# The image every judge job runs in: Python, Node (for the artifact actions), git, a Docker CLI to
# start sandbox containers, and the judge itself at /opt/morphogen. Build from the repository root.
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates jq nodejs \
 && rm -rf /var/lib/apt/lists/*
COPY e2e/docker /usr/local/bin/docker
COPY e2e/cosign /usr/local/bin/cosign
COPY e2e/judge-requirements.txt /tmp/req.txt
COPY e2e/wheels /tmp/wheels
RUN pip install --no-cache-dir --no-index --find-links /tmp/wheels -r /tmp/req.txt && rm -rf /tmp/wheels
COPY judge /opt/morphogen/judge
COPY schemas /opt/morphogen/schemas
ENV PYTHONPATH=/opt/morphogen
