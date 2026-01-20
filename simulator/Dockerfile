FROM python:3.9-slim

# Install FFmpeg and DB dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python libs
RUN pip install psycopg2-binary toml yt-dlp

COPY simulate.py .
COPY download_videos.py .

CMD ["python", "-u", "simulate.py"]
