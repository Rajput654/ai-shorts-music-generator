import cv2
import ffmpeg
import subprocess
import os
import logging

# Set up logging to catch errors during automated runs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class VideoAnalyzer:
    def __init__(self, video_path, output_dir="workspace"):
        self.video_path = video_path
        self.output_dir = output_dir
        self.raw_audio_path = os.path.join(output_dir, "raw_audio.wav")
        self.vocals_path = os.path.join(output_dir, "htdemucs", "raw_audio", "vocals.wav")
        
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

    def extract_audio(self):
        """Extracts the full audio track from the video."""
        logging.info("Extracting raw audio using FFmpeg...")
        try:
            (
                ffmpeg
                .input(self.video_path)
                .output(self.raw_audio_path, acodec='pcm_s16le', ac=2, ar='44100')
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            logging.info(f"Audio successfully extracted to {self.raw_audio_path}")
            return True
        except ffmpeg.Error as e:
            logging.error(f"FFmpeg error: {e.stderr.decode('utf8')}")
            return False

    def separate_vocals(self):
        """Uses Meta's Demucs to isolate vocals from the background track."""
        logging.info("Running Demucs to isolate vocals (this may take a moment)...")
        try:
            # Calling demucs via subprocess as it's the most stable way for local free tools
            subprocess.run(
                ["demucs", "--two-stems=vocals", "-o", self.output_dir, self.raw_audio_path],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            logging.info("Vocals successfully isolated.")
            return True
        except subprocess.CalledProcessError as e:
            logging.error(f"Demucs failed: {e.stderr.decode()}")
            return False

    def calculate_visual_pacing(self):
        """Analyzes video frames to detect cuts and estimate a target BPM."""
        logging.info("Analyzing video cuts to determine pacing...")
        cap = cv2.VideoCapture(self.video_path)
        
        if not cap.isOpened():
            logging.error("Failed to open video for OpenCV analysis.")
            return None

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_sec = total_frames / fps

        cut_count = 0
        prev_hist = None

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Convert to grayscale and calculate histogram for cut detection
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
            cv2.normalize(hist, hist)

            if prev_hist is not None:
                # Compare current frame to previous frame
                diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                # A sudden drop in correlation usually indicates a scene cut
                if diff < 0.85: 
                    cut_count += 1

            prev_hist = hist

        cap.release()
        
        # Estimate BPM based on cut frequency (Cuts per minute)
        # Base pacing of 80 BPM, adding speed for faster, frequent cuts
        cuts_per_minute = (cut_count / duration_sec) * 60 if duration_sec > 0 else 0
        target_bpm = min(max(int(80 + (cuts_per_minute * 0.5)), 60), 160) # Clamp between 60-160 BPM
        
        logging.info(f"Detected {cut_count} cuts. Estimated Target BPM: {target_bpm}")
        return target_bpm

    def run_pipeline(self):
        if self.extract_audio():
            self.separate_vocals()
            bpm = self.calculate_visual_pacing()
            return {"vocals_path": self.vocals_path, "target_bpm": bpm}
        return None

# Execution Block
if __name__ == "__main__":
    # Replace with a test video in your directory
    analyzer = VideoAnalyzer(video_path="input_test_video.mp4") 
    results = analyzer.run_pipeline()
    print(f"\nPhase 1 Complete. Data to pass to Phase 2: {results}")