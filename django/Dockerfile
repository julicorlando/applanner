FROM postgres:16-bookworm AS postgres_tools

FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 liblz4-1 libzstd1 postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

COPY --from=postgres_tools /usr/lib/postgresql/16/bin/pg_dump /usr/local/bin/pg_dump
COPY --from=postgres_tools /usr/lib/postgresql/16/bin/pg_restore /usr/local/bin/pg_restore
COPY --from=postgres_tools /usr/lib/postgresql/16/bin/psql /usr/local/bin/psql
RUN pg_dump --version && pg_restore --version && psql --version

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

COPY . /app
RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R appuser:appuser /app

USER appuser
EXPOSE 8000

CMD ["/app/entrypoint.sh"]
