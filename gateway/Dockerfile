# Build context is the repo root: docker build -f gateway/Dockerfile .
FROM python:3.12-slim

# This image is the only place a real API key exists (ARCHITECTURE.md section 8),
# so it stays minimal and runs unprivileged.
RUN useradd --create-home --uid 10001 ares
WORKDIR /app

COPY gateway/requirements.txt /app/gateway/requirements.txt
RUN pip install --no-cache-dir -r /app/gateway/requirements.txt

COPY ares/ /app/ares/
COPY gateway/ /app/gateway/

USER ares
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ARES_GATEWAY_HOST=0.0.0.0 \
    ARES_GATEWAY_PORT=8080 \
    ARES_ADMIN_HOST=127.0.0.1 \
    ARES_ADMIN_PORT=8081

# 8080 faces labnet. 8081 (run registration + kill lever 1) binds to loopback
# and is deliberately NOT exposed: the agent shares a network with this
# container's inside leg and must not be able to un-deny itself.
EXPOSE 8080

CMD ["python", "-m", "gateway.main"]
