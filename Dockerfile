FROM python:3.11-slim-bookworm

WORKDIR /app

# System deps for Playwright and Pillow
RUN apt-get update && apt-get install -y \
    libglib2.0-0 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libjpeg62-turbo libpng16-16 libwebp7 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium browser for services/source_adapters/serp_scraper.py's Playwright
# fallback (used when a serp_scraper source has no SerpAPI key configured).
# --with-deps also covers any Playwright-side apt packages not already
# installed above.
RUN playwright install --with-deps chromium

# Install spaCy model
RUN python -m spacy download en_core_web_sm

COPY backend/ ./backend/
COPY frontend/dist/ ./frontend/dist/
COPY alembic.ini .
COPY alembic/ ./alembic/
# docs/CUSTOM_ADAPTER_GUIDE.md is served at GET /api/docs/adapter (backend/routers/docs.py) —
# without this the in-app Adapter Docs page 404s inside a container.
COPY docs/ ./docs/

# alembic.ini's script_location is relative to the project root (/app), so
# alembic must run from /app, NOT /app/backend — see backend/db/database.py
# and main.py, both of which compute paths (broll_engine.db, tmp/) relative
# to /app (Path(__file__).parent.parent[.parent]), not /app/backend.
CMD ["sh", "-c", "alembic upgrade head && cd backend && uvicorn main:app --host 0.0.0.0 --port 7420"]

EXPOSE 7420
