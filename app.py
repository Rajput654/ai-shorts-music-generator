import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import shutil
import uuid
import logging
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from main import run_agent
from auth import router as auth_router, get_current_user
from database import SessionLocal, VideoJob

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebAPI")

UPLOAD_DIR = "temp_uploads"
STATIC_DIR = "static"

# Ensure all required directories exist at startup
for d in [UPLOAD_DIR, "output", "workspace", STATIC_DIR]:
    os.makedirs(d, exist_ok=True)

# -----------------------------------------------------------------------
# Inline HTML fallback pages
# These are used if the static/ files were not deployed with the container.
# In production, the real HTML files in static/ take precedence.
# -----------------------------------------------------------------------
_MISSING_FILE_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>SynthaVerse</title>
<style>
  body {{ font-family: sans-serif; background: #0a0a0f; color: #f8fafc;
         display: flex; align-items: center; justify-content: center;
         min-height: 100vh; margin: 0; }}
  .box {{ background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);
          border-radius: 16px; padding: 3rem; max-width: 480px; text-align: center; }}
  h1 {{ color: #818cf8; margin-bottom: 1rem; }}
  p  {{ color: #94a3b8; line-height: 1.6; }}
  code {{ background: rgba(255,255,255,0.1); padding: 2px 8px;
          border-radius: 4px; font-size: 0.9rem; }}
</style></head>
<body><div class="box">
  <h1>⚠️ Static Files Missing</h1>
  <p>The HTML frontend files were not found in the <code>static/</code> directory.</p>
  <p>Please make sure your <code>static/</code> folder (containing
     <code>index.html</code>, <code>login.html</code>, <code>signup.html</code>,
     <code>admin.html</code>, <code>styles.css</code>, <code>script.js</code>)
     is committed to your git repository and pushed to Hugging Face.</p>
  <p>The API endpoints at <code>/api/</code> are running normally.</p>
</div></body></html>"""


def _serve_static(filename: str):
    """Serve a file from static/ or return a helpful HTML error page."""
    path = os.path.join(STATIC_DIR, filename)
    if os.path.exists(path):
        return FileResponse(path)
    logger.error(f"Static file not found: {path}")
    return HTMLResponse(
        content=_MISSING_FILE_HTML.format(),
        status_code=200   # 200 so the browser renders the page, not a blank error
    )


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

            final_video_path = await asyncio.to_thread(
                run_agent, input_video=temp_video_path, target_duration=duration
            )

            if not final_video_path or not os.path.exists(final_video_path):
                raise Exception("Agent pipeline failed to produce a final video.")

            file_name = os.path.basename(final_video_path)
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker_task = asyncio.create_task(process_queue_worker())
    logger.info("Queue worker started.")
    yield
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    logger.info("Queue worker stopped.")


# CORS — defaults to * so HF Spaces works out of the box
_raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app = FastAPI(title="AI Music Composer API", version="1.0", lifespan=lifespan)
app.include_router(auth_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Only mount /static if the directory has actual files in it,
# otherwise StaticFiles raises an error on directories with no files.
if any(os.scandir(STATIC_DIR)) if os.path.exists(STATIC_DIR) else False:
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
else:
    logger.warning("static/ directory is empty or missing — /static route not mounted.")


# -----------------------------------------------------------------------
# Page routes — safe fallback if files are missing
# -----------------------------------------------------------------------
@app.get("/")
async def serve_frontend():
    return _serve_static("index.html")

@app.get("/login")
async def serve_login():
    return _serve_static("login.html")

@app.get("/signup")
async def serve_signup():
    return _serve_static("signup.html")

@app.get("/admin")
async def serve_admin():
    return _serve_static("admin.html")


# -----------------------------------------------------------------------
# API routes
# -----------------------------------------------------------------------
@app.post("/api/generate")
async def generate_music(
    video: UploadFile = File(...),
    duration: int = Form(30),
    current_user=Depends(get_current_user)
):
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
    safe_name = os.path.basename(filename)
    file_path = os.path.join("output", safe_name)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="video/mp4")
    raise HTTPException(status_code=404, detail="File not found")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
