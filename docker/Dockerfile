# PostgreSQL for local development. The application database itself is created by
# `scout db-setup`, so the image only starts the server with the maintenance database.
FROM postgres:18-alpine

ENV POSTGRES_USER=scout \
    POSTGRES_PASSWORD=scout \
    TZ=UTC \
    PGTZ=UTC

HEALTHCHECK --interval=5s --timeout=3s --retries=10 \
    CMD pg_isready -U "$POSTGRES_USER" -d postgres || exit 1

EXPOSE 5432
