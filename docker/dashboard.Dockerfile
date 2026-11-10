# Web dashboard and its API (guide Step 10). Built from the repository root by compose.yml:
#   docker compose -f docker/compose.yml up -d --build
# Needs only DATABASE_URL: no LLM, HubSpot or ClickUp credentials.
FROM python:3.14-slim

WORKDIR /app
COPY pyproject.toml requirements.txt README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

ENV DATABASE_URL=postgresql+psycopg://scout:scout@postgres:5432/scout_ai
EXPOSE 8000
# 0.0.0.0 inside the container; compose publishes the port on the host's localhost only.
CMD ["scout", "serve", "--host", "0.0.0.0", "--port", "8000"]
