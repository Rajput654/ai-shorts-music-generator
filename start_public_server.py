import os
import sys
import logging
import threading
import time
from pyngrok import ngrok
import uvicorn

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PublicWebManager")

def initialize_tunnel(port: int):
    """
    Starts the ngrok tunnel to expose the local server ports to the internet.
    We wait a small delay to ensure the local server actually boots first.
    """
    time.sleep(2)  # Give uvicorn a moment to bind to the port
    
    try:
        # If the user has added an ngrok auth token to their .env or system env, use it.
        # It's recommended because ngrok's true free tier now requires it to serve HTML pages nicely.
        token = os.getenv("NGROK_AUTHTOKEN", "")
        if token:
            ngrok.set_auth_token(token)
            logger.info("Authenticated ngrok with provided token.")
        else:
            logger.warning("No NGROK_AUTHTOKEN found in environment.")
            logger.warning("You may see an 'Ngrok Warning' interstitial page when you first visit the site.")
            logger.warning("Sign up for a free token at https://dashboard.ngrok.com and add it to your .env file to skip it.")

        # Open the tunnel
        public_auth_url = ngrok.connect(port)
        
        print("\n" + "="*70)
        print("🌍 YOUR AI COMPOSER WEBSITE IS LIVE!")
        print(f"👉 PUBLIC URL: {public_auth_url.public_url}")
        print("="*70)
        print("Share this link to allow anyone to use your agent.")
        print("Keep this terminal window open to keep the server running.\n")
        
    except Exception as e:
        logger.error(f"Failed to start ngrok tunnel: {e}")
        print("\nAlternative Free Tunnel Options if ngrok fails:")
        print("1. Cloudflare:  cloudflared tunnel --url http://localhost:8000")
        print("2. Localtunnel: npx localtunnel --port 8000")
        print("3. Pinggy (SSH): ssh -p 443 -R0:localhost:8000 a.pinggy.io\n")

if __name__ == "__main__":
    # Load env vars manually here if python-dotenv is present
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    PORT = 8000
    
    # Launch tunnel in background thread
    tunnel_thread = threading.Thread(target=initialize_tunnel, args=(PORT,), daemon=True)
    tunnel_thread.start()

    # Launch FastAPI Server
    logger.info("Starting local backend server...")
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=False)
