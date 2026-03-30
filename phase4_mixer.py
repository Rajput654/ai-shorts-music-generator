import os
import logging
from pydub import AudioSegment, silence
import ffmpeg

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class FinalMixer:
    def __init__(self, original_video, vocals_path, bgm_path, cut_timestamps=None, output_dir="workspace"):
        self.original_video = original_video
        self.vocals_path = vocals_path
        self.bgm_path = bgm_path
        self.cut_timestamps = cut_timestamps or []
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

        logging.info("Applying native O(K) Auto-Ducking logic to background music...")
        
        # 2. Native Auto-Ducking Logic & Visual Sidechain Sync
        # Detect where vocals are actively speaking instead of O(N) checking every 100ms
        nonsilent_ranges = silence.detect_nonsilent(vocals, min_silence_len=200, silence_thresh=threshold_db)
        
        # Create forced ducking ranges for visual impacts (200ms before a visual cut)
        cut_ms_list = [int(ct * 1000) for ct in self.cut_timestamps]
        cut_ranges = [[max(0, cut_ms - 200), cut_ms] for cut_ms in cut_ms_list]
        
        # Merge all ranges where ducking should occur
        all_ranges = nonsilent_ranges + cut_ranges
        all_ranges.sort(key=lambda x: x[0])
        
        merged_ranges = []
        for r in all_ranges:
            if not merged_ranges:
                merged_ranges.append(r)
            else:
                last = merged_ranges[-1]
                if r[0] <= last[1]:
                    merged_ranges[-1] = [last[0], max(last[1], r[1])]
                else:
                    merged_ranges.append(r)

        # Slice and reconstruct the BGM natively
        final_bgm = AudioSegment.empty()
        last_end = 0
        
        for start, end in merged_ranges:
            # Add normal volume portion
            final_bgm += bgm[last_end:start]
            
            # Apply ducking
            duck_amount = 12 if end - start == 200 and start in [c[0] for c in cut_ranges] else abs(ducking_db)
            final_bgm += bgm[start:end] - duck_amount
            last_end = end
            
        # Append any remaining audio tail
        final_bgm += bgm[last_end:]
        ducked_bgm = final_bgm

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