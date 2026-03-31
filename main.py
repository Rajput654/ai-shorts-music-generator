import os
import logging
import time
import uuid
import shutil
from dotenv import load_dotenv

# Load configuration from .env if present
load_dotenv()

# Phase modules will be lazy-loaded inside the run_agent function 
# to prevent OpenBLAS and Torch Out-Of-Memory errors on web server bootup.

# Set up master logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AutoComposerAgent")

def run_agent(input_video, base_workspace="workspace", target_duration=30):
    """
    Runs the entire automated music composition and mixing pipeline.
    """
    # Lazy-load massive models and frameworks only when requested, saving hundreds of MBs of boot RAM
    from phase1_extractor import VideoAnalyzer
    from phase2_composer import AIComposer
    from phase3_generator import MusicGenerator
    from phase4_mixer import FinalMixer

    job_id = str(uuid.uuid4())
    output_dir = os.path.join(base_workspace, f"job_{job_id}")
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    logger.info(f"=== STARTING AUTOMATED COMPOSER AGENT (Job: {job_id}) ===")
    logger.info(f"Target Video: {input_video}")
    logger.info(f"Workspace initialized at: {output_dir}")
    start_time = time.time()

    if not os.path.exists(input_video):
        logger.error(f"Input video '{input_video}' not found. Exiting.")
        return False

    # ---------------------------------------------------------
    # PHASE 1: Extraction & Analysis
    # ---------------------------------------------------------
    logger.info("\n--- INITIATING PHASE 1: EXTRACTION ---")
    analyzer = VideoAnalyzer(video_path=input_video, output_dir=output_dir)
    p1_data = analyzer.run_pipeline()
    
    if not p1_data:
        logger.error("Pipeline aborted during Phase 1.")
        return False

    # ---------------------------------------------------------
    # PHASE 2: AI Composition
    # ---------------------------------------------------------
    logger.info("\n--- INITIATING PHASE 2: COMPOSITION ---")
    composer = AIComposer(
        audio_path=p1_data["vocals_path"], 
        target_bpm=p1_data["target_bpm"],
        visual_context=p1_data.get("visual_context", "")
    )
    p2_data = composer.run_pipeline()
    
    if not p2_data:
        logger.error("Pipeline aborted during Phase 2.")
        return False

    # ---------------------------------------------------------
    # PHASE 3: Music Generation
    # ---------------------------------------------------------
    logger.info("\n--- INITIATING PHASE 3: GENERATION ---")
    generator = MusicGenerator(
        prompt=p2_data["music_prompt"], 
        duration=target_duration, 
        output_dir=output_dir
    )
    bgm_path = generator.generate_track()
    
    if not bgm_path:
        logger.error("Pipeline aborted during Phase 3.")
        return False

    # ---------------------------------------------------------
    # PHASE 4: Mixing & Rendering
    # ---------------------------------------------------------
    logger.info("\n--- INITIATING PHASE 4: MIXING ---")
    mixer = FinalMixer(
        original_video=input_video, 
        vocals_path=p1_data["vocals_path"], 
        bgm_path=bgm_path, 
        cut_timestamps=p1_data.get("cut_timestamps", []),
        output_dir=output_dir
    )
    final_video_path = mixer.run_pipeline()
    
    if not final_video_path:
        logger.error("Pipeline aborted during Phase 4.")
        return False

    # ---------------------------------------------------------
    # FINISH & CLEANUP
    # ---------------------------------------------------------
    master_output_dir = "output"
    if not os.path.exists(master_output_dir):
        os.makedirs(master_output_dir)
        
    final_dest = os.path.join(master_output_dir, f"FINAL_{job_id}.mp4")
    try:
        shutil.move(final_video_path, final_dest)
    except Exception as e:
        logger.error(f"Failed to move final video: {e}")
        final_dest = final_video_path
        
    # Cleanup memory leaks from disk
    try:
        shutil.rmtree(output_dir)
        logger.info(f"Cleaned up temporary workspace: {output_dir}")
    except Exception as e:
        logger.error(f"Failed to cleanup workspace {output_dir}: {e}")

    elapsed_time = round(time.time() - start_time, 2)
    logger.info("\n=================================================")
    logger.info(f"✅ AGENT RUN COMPLETE IN {elapsed_time} SECONDS")
    logger.info(f"🎬 Final Video Ready: {final_dest}")
    logger.info("=================================================")
    
    return final_dest

if __name__ == "__main__":
    # Point this to the video you want to process
    TARGET_VIDEO = "input_test_video.mp4" 
    
    # Run the agent (defaulting to duration from env, fallback 30 seconds)
    duration = int(os.getenv("TARGET_DURATION", "30"))
    run_agent(input_video=TARGET_VIDEO, target_duration=duration)