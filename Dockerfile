FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS builder

WORKDIR /build

COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir setuptools==80.10.2 \
    && pip install --no-cache-dir --prefix=/install \
        -r requirements.txt -c requirements-lock.txt

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install \
    --no-deps --no-build-isolation .

FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/app/data/u_calc.db

WORKDIR /app

COPY --from=builder /install /usr/local
COPY docker-entrypoint.sh /usr/local/bin/u-calc-entrypoint

RUN addgroup --system ucalc \
    && adduser --system --ingroup ucalc --home /app ucalc \
    && mkdir -p /app/data \
    && chown -R ucalc:ucalc /app/data \
    && chmod 0755 /usr/local/bin/u-calc-entrypoint

VOLUME ["/app/data"]

ENTRYPOINT ["u-calc-entrypoint"]
CMD ["u-calc-bot"]
