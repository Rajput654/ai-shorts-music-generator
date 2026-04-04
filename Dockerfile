# Use official Python image (Debian Trixie based)
FROM python:3.10-slim

# Hugging Face Spaces requires a non-root user with UID 1000
RUN useradd -m -u 1000 user

ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

# -----------------------------------------------------------------------
# System dependencies.
# No FFmpeg dev headers needed:
#   - ffmpeg-python uses the static binary below as a subprocess wrapper.
#   - PyAV (av) is installed via a modern binary wheel that bundles its
#     own FFmpeg libs, requiring zero system headers.
# -----------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libsndfile1 \
    pkg-config \
    gcc \
    g++ \
    wget \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Install static FFmpeg binary (used by ffmpeg-python at runtime)
RUN wget -q https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz && \
    tar xf ffmpeg-release-amd64-static.tar.xz && \
    mv ffmpeg-*-amd64-static/ffmpeg /usr/local/bin/ && \
    mv ffmpeg-*-amd64-static/ffprobe /usr/local/bin/ && \
    rm -rf ffmpeg-* && \
    chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe

WORKDIR $HOME/app
RUN chown -R user:user $HOME/app
USER user

COPY --chown=user:user requirements.txt .

# -----------------------------------------------------------------------
# Python dependency install strategy — ORDER IS CRITICAL:
#
# The stable audiocraft PyPI release hard-pins av==11.0.0, which no
# longer has any binary wheels on PyPI (only versions >=12 are available).
# Building av from source requires FFmpeg dev headers which we cannot
# install on Trixie without dependency conflicts.
#
# Solution: install audiocraft with --no-deps, then satisfy its
# dependencies manually via requirements.txt using av>=12 which works
# at runtime. av 12/13/14 is API-compatible with what audiocraft uses.
#
# Step 1: upgrade pip
# Step 2: install all deps from requirements.txt (includes av>=12, torch,
#         all audiocraft transitive deps declared explicitly)
# Step 3: install audiocraft itself with --no-deps so pip never sees the
#         pinned av==11.0.0 constraint and never tries to build from source
# -----------------------------------------------------------------------
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --no-deps \
        git+https://github.com/facebookresearch/audiocraft.git

COPY --chown=user:user . .

RUN mkdir -p temp_uploads workspace output static

EXPOSE 7860
ENV PORT=7860

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
