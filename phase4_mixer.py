import os
import logging
from pydub import AudioSegment
import ffmpeg

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class FinalMixer:
    def __init__(self, original_video, vocals_path, bgm_path, output_dir="workspace"):
        self.original_video = original_video
        self.vocals_path = vocals_path
        self.bgm_path = bgm_path
        self.output_dir = output_dir
        
        self.mixed_audio_path = os.path.join(output_dir, "final_mixed_audio.wav")
        self.final_video_path = os.path.join(output_dir, "FINAL_OUTPUT.mp4")

    def auto_duck_and_mix(self, ducking_db=-12, threshold_db=-40):
        """
        Loops the BGM to match video length, and applies auto-ducking 
        so the music gets quieter when vocals are present.
        """
        logging.info("Loading audio files into the mixing desk...")
        try:
            vocals = AudioSegment.from_file(self.vocals_path)
            bgm = AudioSegment.from_file(self.bgm_path)
        except Exception as e:
            logging.error(f"Failed to load audio files: {e}")
            return False

        if len(bgm) == 0 or len(vocals) == 0:
            logging.error("One of the audio tracks is empty (duration 0).")
            return False

        # 1. Loop BGM if it's shorter than the vocals (common for generated shorts audio)
        if len(bgm) < len(vocals):
            logging.info("BGM is shorter than video. Looping background music seamlessly...")
            # Calculate how many times we need to loop, add 1 for safety
            loop_count = (len(vocals) // len(bgm)) + 1
            # Crossfade the loops slightly so it doesn't "click" on the restart
            looped_bgm = bgm
            for _ in range(loop_count - 1):
                looped_bgm = looped_bgm.append(bgm, crossfade=500)
            bgm = looped_bgm

        # Trim exact length unconditionally to prevent duration drift
        bgm = bgm[:len(vocals)]

        # Normalize both tracks so we are starting from a consistent volume level
        vocals = vocals.normalize()
        bgm = bgm.normalize() - 5 # Drop base BGM volume a bit

        logging.info("Applying Auto-Ducking to background music...")
        
        # 2. The Auto-Ducking Logic
        chunk_size = 100 # Analyze audio in 100 millisecond chunks
        chunks = []
        
        for i in range(0, len(vocals), chunk_size):
            vocal_chunk = vocals[i:i + chunk_size]
            bgm_chunk = bgm[i:i + chunk_size]
            
            # If the vocals in this tiny chunk are louder than the threshold (someone is speaking)
            if vocal_chunk.dBFS > threshold_db:
                # Lower the BGM volume
                chunks.append((bgm_chunk - abs(ducking_db)).raw_data)
            else:
                # Keep normal volume during silence/breaths
                chunks.append(bgm_chunk.raw_data)

        # Reconstruct the audio segment from raw bytes (O(N) time)
        raw_ducked_data = b"".join(chunks)
        ducked_bgm = bgm._spawn(raw_ducked_data)

        # 3. Mix the tracks together
        logging.info("Mixing vocals and processed BGM together...")
        final_audio = vocals.overlay(ducked_bgm)
        
        # Export the mixed audio
        final_audio.export(self.mixed_audio_path, format="wav")
        logging.info(f"Mixed audio saved to {self.mixed_audio_path}")
        return True

    def render_final_video(self):
        """Attaches the perfectly mixed audio track back onto the original video."""
        logging.info("Muxing final audio with the original video frames...")
        try:
            # Load the original video (just the video stream)
            video_stream = ffmpeg.input(self.original_video).video
            
            # Load our newly mixed audio stream
            audio_stream = ffmpeg.input(self.mixed_audio_path).audio
            
            # Combine them
            (
                ffmpeg
                .output(video_stream, audio_stream, self.final_video_path, 
                        vcodec='copy', # Copy video without re-encoding (blazing fast)
                        acodec='aac',  # Encode audio to standard AAC format
                        strict='experimental')
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            logging.info(f"SUCCESS! Final video rendered at: {self.final_video_path}")
            return self.final_video_path
            
        except ffmpeg.Error as e:
            logging.error(f"FFmpeg muxing failed: {e.stderr.decode('utf8')}")
            return None

    def run_pipeline(self):
        if self.auto_duck_and_mix():
            return self.render_final_video()
        return None

# Execution Block
if __name__ == "__main__":
    # Simulating the inputs gathered from Phase 1, 2, and 3
    test_video = "input_test_video.mp4" 
    test_vocals = "workspace/htdemucs/raw_audio/vocals.wav"
    test_bgm = "workspace/generated_bgm.wav"
    
    # Create dummy files for the script to run without crashing if you test it empty
    for path in [test_vocals, test_bgm]:
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            # Create a 1-second silent audio file just so PyDub doesn't crash on test
            AudioSegment.silent(duration=1000).export(path, format="wav")
    
    # Dummy video file creation if missing
    if not os.path.exists(test_video):
        with open(test_video, 'w') as f: f.write("dummy")

    mixer = FinalMixer(original_video=test_video, vocals_path=test_vocals, bgm_path=test_bgm)
    final_output = mixer.run_pipeline()
    
    print(f"\n✅ Pipeline Complete! Output Video: {final_output}")