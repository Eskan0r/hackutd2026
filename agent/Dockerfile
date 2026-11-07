# Build context is the repo root: docker build -f agent/Dockerfile .
# The sandbox. Run with gVisor (runsc), non-root, cap_drop ALL, read-only
# rootfs, no Docker socket (ARCHITECTURE.md section 7).
FROM python:3.12-slim

RUN useradd --create-home --uid 10002 agent
WORKDIR /app

COPY agent/requirements.txt /app/agent/requirements.txt
RUN pip install --no-cache-dir -r /app/agent/requirements.txt

# Only the agent package is copied. The `ares` package -- and with it every
# event-writing code path -- is absent from this image on purpose: the event
# volume is never mounted here (ARCHITECTURE.md section 3), so nothing the agent
# runs can forge, truncate or suppress evidence.
COPY agent/ /app/agent/

USER agent
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ARES_WORKSPACE=/workspace

# No ENTRYPOINT: the control plane invokes the harness per trial with the goal,
# driver and caps for that trial.
CMD ["python", "-m", "agent.harness", "--help"]
