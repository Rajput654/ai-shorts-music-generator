# Use official Python image designed for heavy ML workloads (debian-based)
FROM python:3.10-slim

# Hugging Face Spaces environment requires a non-root user
# Set up a new user named "user" with user ID 1000
RUN useradd -m -u 1000 user

# Set environmental variables safely
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

# Install system-level dependencies for audio/video processing
# Note: Using FFmpeg 6.x for compatibility with PyAV 11.0.0
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libsndfile1 \
    pkg-config \
    gcc \
    g++ \
    wget \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Install FFmpeg 6.1 from static build (compatible with PyAV 11.0.0)
RUN wget https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz && \
    tar xf ffmpeg-release-amd64-static.tar.xz && \
    mv ffmpeg-*-amd64-static/ffmpeg /usr/local/bin/ && \
    mv ffmpeg-*-amd64-static/ffprobe /usr/local/bin/ && \
    rm -rf ffmpeg-* && \
    chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe

# Install FFmpeg development libraries (version 6.x from Debian testing)
RUN echo "deb http://deb.debian.org/debian bookworm main" > /etc/apt/sources.list.d/bookworm.list && \
    apt-get update && apt-get install -y --no-install-recommends \
    -t bookworm \
    libavformat-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavutil-dev \
    libavfilter-dev \
    libswscale-dev \
    libswresample-dev \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory to the user's home directory
WORKDIR $HOME/app

# Change ownership of the app directory to the new non-root user
RUN chown -R user:user $HOME/app

# Switch to the non-root user
USER user

# Copy the requirements file into the container
COPY --chown=user:user requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application files
COPY --chown=user:user . .

# Create essential directories required by the application script
RUN mkdir -p temp_uploads workspace output static

# Expose the correct port for Hugging Face Spaces
EXPOSE 7860

# Define the default port environment variable explicitly
ENV PORT=7860

# Start the FastAPI application via uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
