# AI Shorts Music Generator

An automated, full-stack AI orchestration pipeline designed to ingest short-form video content, visually analyze its context, compose context-aware background scores, and deliver a perfectly mixed final video asset. 

This repository is structured as a production-ready, containerized Micro-SaaS foundation, complete with multi-user authentication, data persistence, and a modular background processing pipeline.

---

## 🚀 Key Features & Architecture

The application is engineered using a decoupled, 4-stage processing pipeline that ensures reliability, easy debugging, and horizontal scalability:

*   **Phase 1: Extractor (`phase1_extractor.py`)** – Ingests the target video file, validates constraints, and extracts visual frames, pacing metadata, and key environmental indicators.
*   **Phase 2: Composer (`phase2_composer.py`)** – Translates the extracted visual data into a musical composition blueprint (determining mood, tempo, genre, and emotional progression).
*   **Phase 3: Generator (`phase3_generator.py`)** – Orchestrates state-of-the-art audio generation models to synthesize the high-quality background audio tracks.
*   **Phase 4: Mixer (`phase4_mixer.py`)** – Safely blends the generated audio with the video's original sound, adjusting levels and synchronization to export a seamless final asset.

### Commercial-Grade SaaS Infrastructure Included:
*   **User Management:** Full user registration, login, and secure session state handling (`auth.py`, `signup.html`, `login.html`).
*   **Database Persistence:** Built-in persistence layers (`database.py`) to manage user states, process logs, and asset histories.
*   **Containerized Architecture:** Fully dockerized configuration (`Dockerfile`, `.dockerignore`) for instant, single-command cloud deployment.
*   **Modern Admin Console:** Includes a custom dashboard (`admin.html`) to oversee system usage and pipeline resource allocation.

---

## 📂 Project Structure

```text
├── static/                 # Frontend Assets & Web UI
│   ├── index.html          # Main Application Dashboard
│   ├── login.html          # User Authentication Entry
│   ├── signup.html         # User Registration Page
│   ├── admin.html          # Administrative System View
│   ├── styles.css          # Core Application UI Styling
│   └── script.js           # Frontend Logic & API Integration
├── app.py                  # Core Web Server & API Framework
├── main.py                 # Core Engine Entry Point
├── auth.py                 # Security & Session Authentication Logic
├── database.py             # Data Persistence Layer Setup
├── phase1_extractor.py     # Target Video Feature Extraction Module
├── phase2_composer.py      # Dynamic Musical Directing Module
├── phase3_generator.py      # Audio Synthesis Engine
├── phase4_mixer.py         # Audio/Video Synthesis & Sync Layer
├── start_public_server.py  # Production Web Server Entry
├── Dockerfile              # Docker Container Build Specification
├── .dockerignore           # Optimized Build Exclusions
├── .gitignore              # Source Code Exclusion Manifest
└── requirements.txt        # Python System Dependencies
