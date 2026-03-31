document.addEventListener("DOMContentLoaded", () => {
    // --- Auth Check ---
    const token = localStorage.getItem("synthaverse_token");
    if (!token) {
        window.location.href = "/login";
        return;
    }

    // Verify token validity and set UI roles
    fetch("/api/auth/me", {
        headers: { "Authorization": `Bearer ${token}` }
    })
    .then(res => {
        if (!res.ok) throw new Error("Invalid token");
        return res.json();
    })
    .then(data => {
        document.getElementById("user-nav").style.display = "block";
        document.getElementById("username-display").innerText = data.username;
        if (data.role === "admin") {
            document.getElementById("admin-link").style.display = "inline-flex";
        }
    })
    .catch(() => {
        localStorage.removeItem("synthaverse_token");
        window.location.href = "/login";
    });

    window.logout = function() {
        localStorage.removeItem("synthaverse_token");
        window.location.href = "/login";
    };

    // DOM Elements
    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("video-upload");
    const fileInfo = document.getElementById("file-info");
    const generateBtn = document.getElementById("generate-btn");
    const targetDuration = document.getElementById("target-duration");

    const uploadSection = document.getElementById("upload-section");
    const loadingSection = document.getElementById("loading-section");
    const resultSection = document.getElementById("result-section");
    const loadingStatus = document.getElementById("loading-status");
    
    const outputVideo = document.getElementById("output-video");
    const downloadBtn = document.getElementById("download-btn");
    const resetBtn = document.getElementById("reset-btn");

    let selectedFile = null;

    // --- Drag & Drop Handling ---
    ["dragenter", "dragover", "dragleave", "drop"].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ["dragenter", "dragover"].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.add("dragover"), false);
    });

    ["dragleave", "drop"].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.remove("dragover"), false);
    });

    dropZone.addEventListener("drop", (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        handleFiles(files);
    });

    fileInput.addEventListener("change", (e) => {
        handleFiles(e.target.files);
    });

    function handleFiles(files) {
        if (files.length === 0) return;
        
        const file = files[0];
        if (!file.type.startsWith("video/")) {
            alert("Please upload a valid video file.");
            return;
        }

        selectedFile = file;
        fileInfo.textContent = `Selected: ${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB)`;
        generateBtn.disabled = false;
        
        // Add a nice visual pop to the button when active
        generateBtn.style.transform = "scale(1.02)";
        setTimeout(() => generateBtn.style.transform = "scale(1)", 200);
    }

    // --- Utility to switch screens with smooth transition ---
    function showSection(sectionToShow) {
        [uploadSection, loadingSection, resultSection].forEach(section => {
            if (section === sectionToShow) {
                section.classList.remove("hidden");
                // Trigger reflow to restart translate animation
                void section.offsetWidth; 
                section.style.opacity = 1;
                section.style.transform = "translateY(0)";
            } else {
                section.classList.add("hidden");
            }
        });
    }

    // --- Generation Flow ---
    generateBtn.addEventListener("click", async () => {
        if (!selectedFile) return;

        showSection(loadingSection);
        
        // Simulated progress messages
        const msgs = [
            "Analyzing visual rhythm...",
            "Matching BPM to scene cuts...",
            "Generating AI instruments...",
            "Mixing final audio stems...",
            "Rendering final composition..."
        ];
        
        let msgIndex = 0;
        const msgInterval = setInterval(() => {
            msgIndex = (msgIndex + 1) % msgs.length;
            loadingStatus.textContent = msgs[msgIndex];
        }, 5000);

        try {
            const formData = new FormData();
            formData.append("video", selectedFile);
            formData.append("duration", targetDuration.value || 30);

            // Execute the fetch with secure token
            const response = await fetch("/api/generate", {
                method: "POST",
                headers: { "Authorization": `Bearer ${token}` },
                body: formData
            });

            if (!response.ok) {
                clearInterval(msgInterval);
                const errorData = await response.json();
                throw new Error(errorData.detail || "Server failed to queue the video job.");
            }

            const data = await response.json();
            const jobId = data.job_id;
            
            // Start polling the server for the heavy inference API
            const pollInterval = setInterval(async () => {
                try {
                    const statusRes = await fetch(`/api/jobs/${jobId}`, {
                        headers: { "Authorization": `Bearer ${token}` }
                    });
                    
                    if (!statusRes.ok) throw new Error("Failed to check generation status. Are we still online?");
                    
                    const jobData = await statusRes.json();
                    
                    if (jobData.status === "completed") {
                        clearInterval(pollInterval);
                        clearInterval(msgInterval);
                        
                        // Set up result section
                        outputVideo.src = jobData.video_url;
                        downloadBtn.href = jobData.video_url;
                        
                        showSection(resultSection);
                        outputVideo.load();
                    } else if (jobData.status === "failed") {
                        clearInterval(pollInterval);
                        clearInterval(msgInterval);
                        throw new Error(jobData.error || "The AI Pipeline failed to process your video.");
                    }
                    // If processing, just let it naturally run the next polling cycle.
                } catch (pollErr) {
                    clearInterval(pollInterval);
                    clearInterval(msgInterval);
                    console.error(pollErr);
                    alert(`Job interrupted: ${pollErr.message}`);
                    showSection(uploadSection);
                }
            }, 3000); // Poll every 3 seconds

        } catch (error) {
            clearInterval(msgInterval);
            console.error(error);
            alert(`Error generating video: ${error.message}`);
            showSection(uploadSection);
        }
    });

    // --- Reset ---
    resetBtn.addEventListener("click", () => {
        selectedFile = null;
        fileInput.value = "";
        fileInfo.textContent = "No file selected";
        generateBtn.disabled = true;
        outputVideo.src = "";
        showSection(uploadSection);
    });
});
