FROM python:3.12-slim AS production
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BG_NO_DOTENV=1
WORKDIR /app
COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/breakglass /app/backend/breakglass
RUN pip install --no-cache-dir /app/backend && useradd --uid 10001 --create-home argus
COPY deploy/api_start.py /app/api_start.py
USER argus
EXPOSE 8000
CMD ["python", "/app/api_start.py"]
