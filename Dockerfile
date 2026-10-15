FROM python:3.11-slim

# Install OpenJDK headless (for JPype / MPXJ mpp parsing), libpq, unixodbc, and curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless \
    curl \
    gnupg2 \
    libpq5 \
    unixodbc \
    unixodbc-dev \
    && ( \
        curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
        && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
        && apt-get update \
        && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
        || true \
    ) \
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
ENV JAVA_HOME=/usr/lib/jvm/default-java
ENV JVM_PATH=""

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
