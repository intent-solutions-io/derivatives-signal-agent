# Derivatives Signal Agent - Production Dockerfile
FROM python:3.11-slim

# Security: Run as non-root user
RUN useradd --create-home --shell /bin/bash agent

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=agent:agent . .

# Create data directory for SQLite
RUN mkdir -p /app/data && chown agent:agent /app/data

# Switch to non-root user
USER agent

# Environment defaults
ENV PYTHONUNBUFFERED=1

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()" || exit 1

# Default: loop mode (override with --serve for API)
CMD ["python", "main.py", "--config", "/app/config.yaml"]
