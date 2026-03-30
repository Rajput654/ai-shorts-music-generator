import whisper
import requests
import json
import logging
import os
from tenacity import retry, stop_after_attempt, wait_exponential

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class AIComposer:
    def __init__(self, audio_path, target_bpm, visual_context=""):
        self.audio_path = audio_path
        self.target_bpm = target_bpm
        self.visual_context = visual_context
        # We use the 'base' model for speed and low VRAM usage. 
        # For a short video, this is usually accurate enough.
        self.whisper_model_size = os.getenv("WHISPER_MODEL", "base")
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
        self.music_prompt = ""

    def transcribe_audio(self):
        """Transcribes the isolated vocals to understand the video's topic."""
        logging.info(f"Loading Whisper model '{self.whisper_model_size}' for transcription...")
        try:
            # Load model and transcribe
            model = whisper.load_model(self.whisper_model_size)
            result = model.transcribe(self.audio_path)
            transcript = result["text"].strip()
            
            if not transcript:
                logging.warning("Transcription empty. Video might have no dialogue.")
                return "No dialogue. Focus on visual pacing."
            
            logging.info(f"Transcription complete: '{transcript[:50]}...'")
            return transcript
            
        except FileNotFoundError:
             logging.error(f"Audio file not found at {self.audio_path}. Did Phase 1 complete?")
             return None
        except Exception as e:
            logging.error(f"Whisper transcription failed: {e}")
            return None

    def generate_music_prompt(self, transcript):
        """Uses a local LLM via Ollama to write a specific prompt for MusicGen."""
        logging.info("Consulting the LLM Composer to write the music prompt...")
        
        # System prompt designed specifically to format output for AudioCraft/MusicGen
        system_instructions = (
            "You are an expert music producer scoring a video. "
            "Analyze the transcript, the visual context, and the target BPM. "
            "Output ONLY a comma-separated list of musical descriptors (genre, mood, instruments). "
            "Do not include conversational text like 'Here is the prompt'. "
            f"Mandatory requirement: Include '{self.target_bpm} BPM' at the start."
        )
        
        user_prompt = f"Transcript context: {transcript}\nVisual context: {self.visual_context}"

        payload = {
            "model": "llama3",
            "prompt": f"{system_instructions}\n\n{user_prompt}",
            "stream": False
        }

        @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
        def _make_request():
            response = requests.post(self.ollama_url, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()

        try:
            response_data = _make_request()
            raw_prompt = response_data.get("response", "").strip()
            
            # Fallback if the LLM gets too chatty despite instructions
            if "Here is" in raw_prompt or raw_prompt.count(",") < 2:
                 logging.warning("LLM output formatting poor. Applying strict formatting.")
                 self.music_prompt = f"{self.target_bpm} BPM, cinematic background music, atmospheric, synth, bass"
            else:
                 self.music_prompt = raw_prompt
                 
            logging.info(f"Final Music Prompt Generated: [{self.music_prompt}]")
            return self.music_prompt

        except requests.exceptions.ConnectionError:
            logging.error("Failed to connect to Ollama after retries. Is the Ollama app running in the background?")
            # Dynamic fallback based on visual context
            mood = "neutral, ambient"
            if "dark" in self.visual_context: mood = "atmospheric, dark, cinematic"
            if "bright" in self.visual_context: mood = "upbeat, happy, pop"
            if "vibrant" in self.visual_context: mood = "energetic, electronic, synth"
            if "slow" in self.visual_context: mood = "lofi, relaxing, slow beat"
            if "energetic" in self.visual_context: mood = "rock or action, intense, fast drums"
            
            self.music_prompt = f"{self.target_bpm} BPM, {mood} background music"
            return self.music_prompt
            
        except Exception as e:
            logging.error(f"LLM Prompt generation failed: {e}")
            return None

    def run_pipeline(self):
        transcript = self.transcribe_audio()
        if transcript is not None:
            prompt = self.generate_music_prompt(transcript)
            return {"music_prompt": prompt, "target_bpm": self.target_bpm}
        return None

# Execution Block
if __name__ == "__main__":
    # Simulating data passed from Phase 1
    # Replace with the actual path to the vocals extracted in Phase 1
    test_vocals_path = "workspace/htdemucs/raw_audio/vocals.wav" 
    test_bpm = 110
    
    # Create a dummy file for testing if it doesn't exist
    if not os.path.exists(test_vocals_path):
        os.makedirs(os.path.dirname(test_vocals_path), exist_ok=True)
        with open(test_vocals_path, 'w') as f:
            f.write("dummy")

    composer = AIComposer(audio_path=test_vocals_path, target_bpm=test_bpm)
    results = composer.run_pipeline()
    
    print(f"\nPhase 2 Complete. Data to pass to Phase 3: {results}")