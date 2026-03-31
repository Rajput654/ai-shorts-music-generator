import os
# Prevent OpenBLAS/Torch from crashing on low-memory/high-core machines
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import shutil
import uuid
import logging
import asyncio
from typing import Optional
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Import the existing agent runner
from main import run_agent

# Import Authentication system
from auth import router as auth_router, get_current_user
from database import SessionLocal, VideoJob

# Initialize FastAPI
app = FastAPI(title="AI Music Composer API", version="1.0")

# Attach the authentication API
app.include_router(auth_router)

# Add CORS middleware to support strict access securely
allowed_origins = os.getenv("ALLOWED_ORIGIN", "http://localhost:7860").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebAPI")

# Ensure required directories exist
UPLOAD_DIR = "temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs("output", exist_ok=True)
os.makedirs("workspace", exist_ok=True)
os.makedirs("static", exist_ok=True)

# Mount the static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def serve_frontend():
    """Serves the main frontend html page."""
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

async def process_queue_worker():
    """Background loop that executes 1 job at a time from the SQLite database."""
    logger.info("Initializing Sequential Video Queue Worker...")
    while True:
        db = SessionLocal()
        try:
            # Fetch the oldest pending job
            job = db.query(VideoJob).filter(VideoJob.status == "pending").first()
            if not job:
                # No jobs, sleep for a few seconds
                await asyncio.sleep(3)
                continue
                
            # Lock the job
            job.status = "processing"
            db.commit()
            
            job_id = job.id
            temp_video_path = job.input_path
            duration = job.duration
            logger.info(f"Worker picked up job {job_id}.")
            
            # RUN THE HEAVY AGENT in a separate thread to prevent freezing the FastAPI asyncio loop
            final_video_path = await asyncio.to_thread(run_agent, input_video=temp_video_path, target_duration=duration)
            
            if not final_video_path or not os.path.exists(final_video_path):
                raise Exception("Agent pipeline failed to produce a final video.")
                
            file_name = os.path.basename(final_video_path)
            
            # Re-fetch because of threading time gaps
            job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
            job.status = "completed"
            job.video_url = f"/api/output/{file_name}"
            db.commit()
            logger.info(f"Job {job_id} finished successfully.")
            
        except Exception as e:
            logger.error(f"Worker encountered a job error: {str(e)}")
            if 'job' in locals() and job:
                try:
                    # Re-fetch securely
                    job = db.query(VideoJob).filter(VideoJob.id == job.id).first()
                    job.status = "failed"
                    job.error = str(e)
                    db.commit()
                except Exception as inner_e:
                    logger.error(f"Worker failed to save error state: {inner_e}")
        finally:
            if 'temp_video_path' in locals() and os.path.exists(temp_video_path):
                try:
                    os.remove(temp_video_path)
                except:
                    pass
            db.close()
            
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(process_queue_worker())

@app.post("/api/generate")
async def generate_music(
    video: UploadFile = File(...),
    duration: int = Form(30),
    current_user = Depends(get_current_user)
):
    """
    Endpoint to receive a video file and enqueue it into the SQLite DB.
    """
    if not video.filename:
        raise HTTPException(status_code=400, detail="No video file provided.")
        
    logger.info(f"Received video upload request: {video.filename} (Target duration: {duration}s)")
    
    file_id = str(uuid.uuid4())
    _, ext = os.path.splitext(video.filename)
    if not ext:
        ext = ".mp4"
    
    temp_video_path = os.path.join(UPLOAD_DIR, f"upload_{file_id}{ext}")
    
    try:
        with open(temp_video_path, "wb") as buffer:
            shutil.copyfileobj(video.file, buffer)
            
        # Register the job in purely stateless SQLite
        db = SessionLocal()
        new_job = VideoJob(
            id=file_id,
            status="pending",
            input_path=temp_video_path,
            duration=duration
        )
        db.add(new_job)
        db.commit()
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
async def get_job_status(job_id: str, current_user = Depends(get_current_user)):
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
async def get_output_video(filename: str):
    """Serve the generated final videos."""
    file_path = os.path.join("output", filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="File not found")

if __name__ == "__main__":
    import uvicorn
    # Use the PORT environment variable if available, otherwise default to 7860 (HF Spaces standard)
    port = int(os.environ.get("PORT", "7860"))
    
    # When run directly, start the server
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
