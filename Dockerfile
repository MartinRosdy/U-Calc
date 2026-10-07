FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/app/data/u_calc.db

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml requirements.txt requirements-lock.txt README.md ./
COPY src ./src
COPY docker-entrypoint.sh /usr/local/bin/u-calc-entrypoint

RUN pip install --no-cache-dir -r requirements.txt -c requirements-lock.txt \
    && pip install --no-cache-dir --no-deps . \
    && addgroup --system ucalc \
    && adduser --system --ingroup ucalc --home /app ucalc \
    && mkdir -p /app/data \
    && chown -R ucalc:ucalc /app/data \
    && chmod 0755 /usr/local/bin/u-calc-entrypoint

VOLUME ["/app/data"]

ENTRYPOINT ["u-calc-entrypoint"]
CMD ["u-calc-bot"]
