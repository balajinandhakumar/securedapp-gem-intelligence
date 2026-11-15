# SecuredApp backend — Dockerfile
# Multi-stage Dockerfile: build stage installs Python packages, runtime stage runs the app.
#
# Keyword management (add/remove/update/delete) is secured with require_operator.
# ADMIN/OPERATOR can manage keywords; VIEWER cannot.

FROM python:3.12-slim AS builder

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies needed for psycopg2-binary
# psycopg2-binary provides prebuilt wheels, so no build-essential needed.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency manifest and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime image
FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install runtime system dependencies (libpq for psycopg2, ca-certificates for TLS, wget for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    ca-certificates \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for the application
RUN groupadd -r securedapp && useradd -r -g securedapp -d /app -s /sbin/nologin securedapp

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source (excluding dev/test artifacts via .dockerignore)
COPY . .

# Ensure the app directory is owned by the non-root user
RUN chown -R securedapp:securedapp /app

USER securedapp

EXPOSE 8000

# Run Alembic migrations, seed the product catalogue, then start Uvicorn
# DATABASE_URL, SECRET_KEY, ENVIRONMENT, AUTH_REQUIRED must be supplied via env.
CMD ["sh", "-c", "python -m alembic upgrade head && python app/seed.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]