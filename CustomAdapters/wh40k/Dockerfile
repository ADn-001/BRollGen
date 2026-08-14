FROM python:3.11-slim-bookworm

# Playwright system deps
RUN apt-get update && apt-get install -y \
    libglib2.0-0 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /adapter

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install chromium
RUN playwright install-deps chromium

# ADAPTER_SCRIPT is the entrypoint — set per-service in docker-compose.yml
ARG ADAPTER_SCRIPT=40k_adapter.py
COPY ${ADAPTER_SCRIPT} ./adapter.py

CMD ["python", "adapter.py"]
