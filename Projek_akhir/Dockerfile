# Build stage
FROM python:3.9-slim as builder

WORKDIR /app

# Install build dependencies
COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt

# Final stage
FROM python:3.9-slim

WORKDIR /app

# Copy wheels from builder
COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .

# Install dependencies
RUN pip install --no-cache /wheels/*

# Copy application code
COPY app/ .

# Create upload directory with proper permissions
RUN mkdir -p uploads && \
    chown -R nobody:nogroup uploads && \
    chmod 755 uploads

# Switch to non-root user
USER nobody

# Health check
HEALTHCHECK --interval=30s --timeout=3s \
  CMD curl -f http://localhost:5000/metrics || exit 1

# Run application
CMD ["python", "main.py"]
