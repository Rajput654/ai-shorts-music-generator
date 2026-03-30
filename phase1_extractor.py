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

    def analyze_visual_content(self):
        """Analyzes video frames to detect cuts, estimate a target BPM, and extract visual context."""
        logging.info("Analyzing video visual content to determine pacing and mood...")
        cap = cv2.VideoCapture(self.video_path)
        
        if not cap.isOpened():
            logging.error("Failed to open video for OpenCV analysis.")
            return 80, "standard video"

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_sec = total_frames / fps if fps > 0 else 1

        cut_count = 0
        prev_hist = None
        
        total_brightness, total_saturation, total_motion = 0, 0, 0
        frame_count = 0
        prev_gray = None

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Use smaller frame for faster feature extraction
            small_frame = cv2.resize(frame, (320, 180))
            gray = cv2.cvtColor(small_frame, cv2.COLOR_BGR2GRAY)
            hsv = cv2.cvtColor(small_frame, cv2.COLOR_BGR2HSV)
            
            # Extract visual traits
            total_brightness += gray.mean()
            total_saturation += hsv[:, :, 1].mean()
            if prev_gray is not None:
                total_motion += cv2.absdiff(gray, prev_gray).mean()
            prev_gray = gray
            frame_count += 1
            
            # Cut detection using histogram
            hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
            cv2.normalize(hist, hist)

            if prev_hist is not None:
                diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                if diff < 0.85: 
                    cut_count += 1

            prev_hist = hist

        cap.release()
        
        # Calculate BPM
        cuts_per_minute = (cut_count / duration_sec) * 60 if duration_sec > 0 else 0
        target_bpm = min(max(int(80 + (cuts_per_minute * 0.5)), 60), 160)
        
        # Calculate Visual Context
        if frame_count > 0:
            avg_brightness = total_brightness / frame_count
            avg_saturation = total_saturation / frame_count
            avg_motion = total_motion / frame_count
            
            brightness_desc = "dark" if avg_brightness < 85 else "bright" if avg_brightness > 170 else "balanced lighting"
            saturation_desc = "muted" if avg_saturation < 60 else "vibrant" if avg_saturation > 140 else "standard colors"
            motion_desc = "slow" if avg_motion < 5 else "energetic" if avg_motion > 15 else "moderate"
            
            visual_context = f"The visuals are {brightness_desc} and {saturation_desc}, with {motion_desc} motion."
        else:
            visual_context = "standard video"

        logging.info(f"Detected {cut_count} cuts. Estimated Target BPM: {target_bpm}")
        logging.info(f"Visual Context: {visual_context}")
        
        return target_bpm, visual_context

    def run_pipeline(self):
        if self.extract_audio():
            self.separate_vocals()
            bpm, visual_context = self.analyze_visual_content()
            return {"vocals_path": self.vocals_path, "target_bpm": bpm, "visual_context": visual_context}
        return None

# Execution Block
if __name__ == "__main__":
    # Replace with a test video in your directory
    analyzer = VideoAnalyzer(video_path="input_test_video.mp4") 
    results = analyzer.run_pipeline()
    print(f"\nPhase 1 Complete. Data to pass to Phase 2: {results}")