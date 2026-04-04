import os
# Prevent OpenBLAS/Torch from crashing on low-memory/high-core machines
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import shutil
import uuid
import logging
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Import the existing agent runner
from main import run_agent

# Import Authentication system
from auth import router as auth_router, get_current_user
from database import SessionLocal, VideoJob

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebAPI")

# Ensure required directories exist at import time
UPLOAD_DIR = "temp_uploads"
for d in [UPLOAD_DIR, "output", "workspace", "static"]:
    os.makedirs(d, exist_ok=True)


async def process_queue_worker():
    """Background loop that executes 1 job at a time from the SQLite database."""
    logger.info("Initializing Sequential Video Queue Worker...")
    while True:
        db = SessionLocal()
        job = None
        temp_video_path = None
        try:
            job = db.query(VideoJob).filter(VideoJob.status == "pending").first()
            if not job:
                await asyncio.sleep(3)
                continue

            job.status = "processing"
            db.commit()

            job_id = job.id
            temp_video_path = job.input_path
            duration = job.duration
            logger.info(f"Worker picked up job {job_id}.")

            # Run heavy agent in a thread so we don't block the asyncio event loop
            final_video_path = await asyncio.to_thread(
                run_agent, input_video=temp_video_path, target_duration=duration
            )

            if not final_video_path or not os.path.exists(final_video_path):
                raise Exception("Agent pipeline failed to produce a final video.")

            file_name = os.path.basename(final_video_path)

            # Re-fetch after thread completes (session may be stale)
            job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
            job.status = "completed"
            job.video_url = f"/api/output/{file_name}"
            db.commit()
            logger.info(f"Job {job_id} finished successfully.")

        except Exception as e:
            logger.error(f"Worker encountered a job error: {str(e)}")
            if job is not None:
                try:
                    job = db.query(VideoJob).filter(VideoJob.id == job.id).first()
                    if job:
                        job.status = "failed"
                        job.error = str(e)
                        db.commit()
                except Exception as inner_e:
                    logger.error(f"Worker failed to save error state: {inner_e}")
        finally:
            if temp_video_path and os.path.exists(temp_video_path):
                try:
                    os.remove(temp_video_path)
                except Exception:
                    pass
            db.close()


# -----------------------------------------------------------------------
# Lifespan context manager (replaces deprecated @app.on_event("startup"))
# -----------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the background queue worker
    worker_task = asyncio.create_task(process_queue_worker())
    logger.info("Queue worker started.")
    yield
    # Shutdown: cancel the worker gracefully
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    logger.info("Queue worker stopped.")


# -----------------------------------------------------------------------
# CORS configuration
# -----------------------------------------------------------------------
# On Hugging Face Spaces the public URL is https://<owner>-<space-name>.hf.space
# Allow that origin plus localhost for local development.
# Set ALLOWED_ORIGINS as a comma-separated list in your HF Space Secrets.
# Example: "https://myuser-myspace.hf.space,http://localhost:7860"
_raw_origins = os.getenv(
    "ALLOWED_ORIGINS",
    # Default: allow all origins so the Space works out-of-the-box.
    # Tighten this in production by setting the env var.
    "*"
)
allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

# -----------------------------------------------------------------------
# App setup
# -----------------------------------------------------------------------
app = FastAPI(title="AI Music Composer API", version="1.0", lifespan=lifespan)

app.include_router(auth_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


# -----------------------------------------------------------------------
# Page routes
# -----------------------------------------------------------------------
@app.get("/")
async def serve_frontend():
    return FileResponse("static/index.html")


@app.get("/login")
async def serve_login():
    return FileResponse("static/login.html")


@app.get("/signup")
async def serve_signup():
    return FileResponse("static/signup.html")


@app.get("/admin")
async def serve_admin():
    return FileResponse("static/admin.html")


# -----------------------------------------------------------------------
# API routes
# -----------------------------------------------------------------------
@app.post("/api/generate")
async def generate_music(
    video: UploadFile = File(...),
    duration: int = Form(30),
    current_user=Depends(get_current_user)
):
    """Receive a video file and enqueue it for processing."""
    if not video.filename:
        raise HTTPException(status_code=400, detail="No video file provided.")

    logger.info(f"Received upload: {video.filename} (duration={duration}s, user={current_user.username})")

    file_id = str(uuid.uuid4())
    _, ext = os.path.splitext(video.filename)
    ext = ext if ext else ".mp4"
    temp_video_path = os.path.join(UPLOAD_DIR, f"upload_{file_id}{ext}")

    try:
        with open(temp_video_path, "wb") as buffer:
            shutil.copyfileobj(video.file, buffer)

        db = SessionLocal()
        try:
            new_job = VideoJob(
                id=file_id,
                status="pending",
                input_path=temp_video_path,
                duration=duration
            )
            db.add(new_job)
            db.commit()
        finally:
            db.close()

        return JSONResponse(status_code=202, content={
            "status": "pending",
            "message": "Video queued for generation. Poll the /jobs endpoint.",
            "job_id": file_id
        })

    except Exception as e:
        logger.error(f"Error during file ingest: {str(e)}")
        if os.path.exists(temp_video_path):
            os.remove(temp_video_path)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str, current_user=Depends(get_current_user)):
    """Polling endpoint for the frontend to check generation progress."""
    db = SessionLocal()
    try:
        job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return JSONResponse(content={
            "id": job.id,
            "status": job.status,
            "video_url": job.video_url,
            "error": job.error
        })
    finally:
        db.close()


@app.get("/api/output/{filename}")
async def get_output_video(filename: str, current_user=Depends(get_current_user)):
    """
    Serve the generated final videos.
    Auth-protected to prevent unauthenticated file enumeration.
    NOTE: FileResponse streams directly from disk - fine for HF Spaces.
    For production, use a CDN or object storage (S3, R2, etc.) instead,
    since HF Spaces disk is ephemeral and files are lost on restart.
    """
    # Sanitize filename to prevent path traversal attacks
    safe_name = os.path.basename(filename)
    file_path = os.path.join("output", safe_name)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="video/mp4")
    raise HTTPException(status_code=404, detail="File not found")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
