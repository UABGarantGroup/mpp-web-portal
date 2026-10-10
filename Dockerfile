FROM python:3.11-slim

# Install OpenJDK headless (for JPype / MPXJ mpp parsing), libpq, and curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code and migrations
COPY backend/ ./backend/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Environment defaults
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV JVM_PATH=""

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
