# Production image for the simulated stock trading platform.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HOST=0.0.0.0 \
    COOKIE_SECURE=1 \
    DEV_SHOW_RESET_LINK=0 \
    APP_DATA_DIR=/data \
    APP_BASE_URL=

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY run.sh ./run.sh
RUN chmod +x run.sh && mkdir -p /data

# SQLite + password-reset log live on the persistent volume at APP_DATA_DIR.
VOLUME ["/data"]
EXPOSE 8000

# Render and similar platforms inject $PORT; bind all interfaces inside the container.
CMD ["sh", "-c", "exec uvicorn --factory app.main:create_app --host 0.0.0.0 --port ${PORT:-8000}"]
