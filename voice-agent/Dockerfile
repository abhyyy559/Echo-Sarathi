# Voice agent worker image.
#
# Runs on LiveKit Cloud (agent deployment) AND in docker-compose. LiveKit Cloud
# requires: glibc base image, non-root user, fixed CMD starting the agent with
# the `start` command, and NO LIVEKIT_URL/API_KEY/API_SECRET baked in (Cloud
# injects those at runtime).
#
# The build context is ./voice-agent. Do not copy `.env*` files: they are
# excluded by .dockerignore and Cloud secrets are injected instead.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Keep the Smart Turn model cache inside /app so the unprivileged user can
    # read it after the pre-download below.
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

# Dependencies first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY agent.py .
COPY app ./app

# Pre-download the Smart Turn v3 weights (~9 MB) so the first live call never
# pays for a HuggingFace download on the media path (Hush models ship inside
# its wheel and need no warmup). Done as root, then chowned to appuser.
# The warmup is best-effort: a failed download must not break the image build
# (the model then simply downloads on the first call instead).
RUN adduser \
        --disabled-password \
        --gecos "" \
        --home "/app" \
        --shell "/sbin/nologin" \
        --uid 10001 \
        appuser \
    && mkdir -p /app/.cache/huggingface \
    && (python -c "from smart_turn_livekit import SmartTurnDetector; SmartTurnDetector()" \
        || echo "warn: Smart Turn warmup skipped; weights will download on first call") \
    && chown -R appuser:appuser /app

# Never run as root (LiveKit Cloud requirement).
USER appuser

# Fixed startup command: production mode. The agent connects to the LiveKit URL
# from the environment (Cloud injects it; compose passes it explicitly).
CMD ["python", "agent.py", "start"]
