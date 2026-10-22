# Postgres with pgvector and Apache AGE. Pin versions during the spike.
FROM apache/age:release_PG16_1.5.0
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*
