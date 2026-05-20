# Stage 1: Build Tailwind CSS
FROM node:20-slim AS css-builder

WORKDIR /build

COPY tailwind.config.js .
COPY app/static/css/input.css ./app/static/css/input.css
COPY app/templates ./app/templates

RUN npx --yes tailwindcss@3.4.17 -i ./app/static/css/input.css -o ./app/static/css/style.css --minify

# Stage 2: Build Python dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 3: Runtime
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gosu \
    libjpeg62-turbo \
    zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

COPY . .
COPY --from=css-builder /build/app/static/css/style.css ./app/static/css/style.css

RUN mkdir -p /app/data /app/uploads && chmod +x /app/entrypoint.sh

EXPOSE 5000

ENV PUID=1000
ENV PGID=1000
ENV PIN=1234

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--worker-class", "gthread", "--timeout", "30", "app:create_app()"]
