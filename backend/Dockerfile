# Backend (FastAPI) image.
# Base: python:3.12-slim (matches the locked stack decision; slim keeps the
# image small while psycopg2-binary ships prebuilt wheels).
#
# We COPY an explicit whitelist instead of relying on a .dockerignore so that
# legacy/dev-only files (tests, .venv, local *.db) never enter the image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first for layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
# - app/            the FastAPI package (entrypoint: app.main:app)
# - migrations/     alembic migrations (`alembic upgrade head`)
# - scripts/        seed_demo.py and friends
# - domain_config_schema.py  imported by seed_demo.py at the backend root
COPY domain_config_schema.py alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY scripts ./scripts

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
