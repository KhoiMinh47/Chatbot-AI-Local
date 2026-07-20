FROM --platform=linux/arm64 python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libmagic1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY parse-data/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r /app/requirements.txt

COPY parse-data /app

EXPOSE 8005
CMD ["python", "main.py"]
