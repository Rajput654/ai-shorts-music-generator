import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import shutil
import uuid
import logging
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from main import run_agent
from auth import router as auth_router, get_current_user
from database import SessionLocal, VideoJob

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebAPI")

UPLOAD_DIR = "temp_uploads"
STATIC_DIR = "static"

for d in [UPLOAD_DIR, "output", "workspace", STATIC_DIR]:
    os.makedirs(d, exist_ok=True)

# ===========================================================================
# INLINE HTML — the full frontend is embedded here so the app works even
# if the static/ directory is not committed to git.
# ===========================================================================

CSS = """
:root {
    --bg-base: #0a0a0f;
    --bg-panel: rgba(255, 255, 255, 0.03);
    --border-color: rgba(255, 255, 255, 0.08);
    --accent: #818cf8;
    --accent-hover: #6366f1;
    --accent-glow: rgba(129, 140, 248, 0.5);
    --text-primary: #f8fafc;
    --text-secondary: #94a3b8;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background-color: var(--bg-base); color: var(--text-primary);
       font-family: 'Outfit', sans-serif; min-height: 100vh; overflow-x: hidden;
       display: flex; justify-content: center; align-items: center; }
.background-wrapper { position: fixed; top:0; left:0; width:100vw; height:100vh;
    z-index:-1; overflow:hidden;
    background: radial-gradient(circle at 50% 50%, #11111a 0%, #0a0a0f 100%); }
.orb { position:absolute; border-radius:50%; filter:blur(100px); opacity:0.5;
       animation: float 20s infinite ease-in-out alternate; }
.orb-1 { width:400px; height:400px; background:#6366f1; top:-100px; left:-100px; }
.orb-2 { width:500px; height:500px; background:#ec4899; bottom:-150px; right:10%; animation-delay:-5s; }
.orb-3 { width:300px; height:300px; background:#06b6d4; top:40%; left:40%; animation-delay:-10s; }
@keyframes float { 0%{transform:translateY(0) scale(1)} 100%{transform:translateY(-50px) scale(1.1)} }
.container { width:100%; max-width:600px; padding:2rem; display:flex; flex-direction:column; gap:2rem; z-index:10; }
header { text-align:center; }
.logo { display:flex; align-items:center; justify-content:center; gap:.75rem;
        font-size:2.5rem; font-weight:800; margin-bottom:.5rem; }
.logo i { color:var(--accent); }
.logo span { background:linear-gradient(90deg,#818cf8,#c084fc);
             -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.subtitle { color:var(--text-secondary); font-size:1.1rem; font-weight:300; }
.glass-panel { background:var(--bg-panel); border:1px solid var(--border-color);
    border-radius:20px; padding:2.5rem; backdrop-filter:blur(20px);
    box-shadow:0 25px 50px -12px rgba(0,0,0,.5); }
.hidden { display:none !important; }
.drag-drop-zone { border:2px dashed rgba(255,255,255,.2); border-radius:15px;
    padding:3rem 1.5rem; text-align:center; transition:all .3s; cursor:pointer;
    background:rgba(0,0,0,.2); display:flex; flex-direction:column; align-items:center;
    gap:1rem; margin-bottom:2rem; }
.drag-drop-zone:hover,.drag-drop-zone.dragover { border-color:var(--accent); background:rgba(129,140,248,.05); }
.upload-icon { font-size:3.5rem; color:var(--accent); transition:transform .3s; }
.drag-drop-zone:hover .upload-icon { transform:translateY(-5px); }
.file-info { margin-top:1rem; font-weight:600; color:#4ade80 !important; }
.settings-group { display:flex; flex-direction:column; gap:.5rem; margin-bottom:2rem; }
.settings-group label { font-size:.95rem; color:var(--text-secondary); font-weight:600; }
.settings-group input { background:rgba(0,0,0,.3); border:1px solid var(--border-color);
    padding:1rem; border-radius:10px; color:var(--text-primary); font-size:1rem;
    outline:none; transition:border-color .3s; width:100%; }
.settings-group input:focus { border-color:var(--accent); box-shadow:0 0 0 2px var(--accent-glow); }
.btn-primary,.submit-btn,.btn-secondary { display:inline-flex; align-items:center;
    justify-content:center; gap:.75rem; padding:.8rem 1.5rem; border-radius:10px;
    font-weight:600; font-size:1rem; cursor:pointer; transition:all .3s; border:none;
    text-decoration:none; font-family:'Outfit',sans-serif; }
.btn-primary { background:rgba(255,255,255,.1); color:var(--text-primary); }
.btn-primary:hover { background:rgba(255,255,255,.2); }
.submit-btn { width:100%; background:linear-gradient(135deg,var(--accent),#c084fc);
    color:white; padding:1.2rem; font-size:1.1rem; box-shadow:0 10px 20px -10px var(--accent); }
.submit-btn:hover:not(:disabled) { transform:translateY(-2px); filter:brightness(1.1); }
.submit-btn:disabled { background:#334155; color:#94a3b8; cursor:not-allowed; }
.btn-secondary { background:#334155; color:white; }
.btn-secondary:hover { background:#475569; }
.auth-form { display:flex; flex-direction:column; gap:1.5rem; }
.error-msg { color:#f87171; text-align:center; font-size:.9rem; }
.loader { display:flex; justify-content:center; margin-bottom:2rem; }
.waveform { display:flex; align-items:center; gap:6px; height:60px; }
.bar { width:6px; background:var(--accent); border-radius:3px; animation:wave 1s ease-in-out infinite; }
.bar:nth-child(1){height:20%;animation-delay:0s}
.bar:nth-child(2){height:60%;animation-delay:.1s;background:#c084fc}
.bar:nth-child(3){height:100%;animation-delay:.2s;background:#ec4899}
.bar:nth-child(4){height:60%;animation-delay:.3s;background:#c084fc}
.bar:nth-child(5){height:20%;animation-delay:.4s}
@keyframes wave{0%,100%{transform:scaleY(.5)}50%{transform:scaleY(1)}}
#loading-section{text-align:center}
#loading-status{color:var(--text-secondary);margin-bottom:2rem}
.progress-container{height:8px;background:rgba(255,255,255,.1);border-radius:4px;overflow:hidden}
.progress-bar{height:100%;width:50%;background:linear-gradient(90deg,var(--accent),#c084fc);
    border-radius:4px;animation:indeterminateProgress 10s cubic-bezier(.1,.7,1,.1) infinite}
@keyframes indeterminateProgress{0%{transform:translateX(-100%)}100%{transform:translateX(200%)}}
#result-section h2{margin-bottom:1.5rem;text-align:center;display:flex;align-items:center;justify-content:center;gap:.5rem}
.video-container{width:100%;border-radius:12px;overflow:hidden;background:#000;
    margin-bottom:1.5rem;border:1px solid var(--border-color);
    aspect-ratio:9/16;max-height:500px;margin-inline:auto}
video{width:100%;height:100%;object-fit:contain}
.action-buttons{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
.table-container{width:100%;border-collapse:collapse;margin-top:1rem;
    background:rgba(0,0,0,.2);border-radius:10px;overflow:hidden}
th,td{padding:1rem;text-align:left;border-bottom:1px solid var(--border-color)}
th{background:rgba(255,255,255,.05);color:var(--accent)}
.role-badge{background:rgba(129,140,248,.2);color:#818cf8;padding:4px 10px;
    border-radius:12px;font-size:.8rem;font-weight:600;text-transform:uppercase}
.role-admin{background:rgba(74,222,128,.2);color:#4ade80}
"""

_HEAD = """<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>{css}</style>""".format(css=CSS)

_ORBS = """<div class="background-wrapper">
  <div class="orb orb-1"></div><div class="orb orb-2"></div><div class="orb orb-3"></div>
</div>"""

INDEX_HTML = f"""<!DOCTYPE html><html lang="en"><head><title>AI Music Composer</title>{_HEAD}</head>
<body>{_ORBS}
<main class="container">
  <header style="display:flex;justify-content:space-between;align-items:start;">
    <div>
      <div class="logo"><i class="fa-solid fa-music"></i><h1>Syntha<span>Verse</span></h1></div>
      <p class="subtitle">Next-gen AI Music Synchronization</p>
    </div>
    <div id="user-nav" style="display:none;text-align:right;">
      <p style="margin-bottom:5px;color:var(--text-secondary);"><i class="fa-solid fa-user"></i> <span id="username-display">User</span></p>
      <div style="display:flex;gap:10px;justify-content:flex-end;">
        <button onclick="logout()" class="btn-secondary" style="padding:5px 10px;font-size:.8rem;">Logout</button>
        <a id="admin-link" href="/admin" class="btn-primary" style="display:none;padding:5px 10px;font-size:.8rem;text-decoration:none;"><i class="fa-solid fa-gauge"></i> Admin</a>
      </div>
    </div>
  </header>

  <section class="glass-panel" id="upload-section">
    <div class="drag-drop-zone" id="drop-zone">
      <i class="fa-solid fa-cloud-arrow-up upload-icon"></i>
      <h2>Drag &amp; Drop your Video</h2><p>or</p>
      <label for="video-upload" class="btn-primary">Browse Files</label>
      <input type="file" id="video-upload" accept="video/*" hidden>
      <p class="file-info" id="file-info">No file selected</p>
    </div>
    <div class="settings-group">
      <label for="target-duration">Target Duration (Seconds)</label>
      <input type="number" id="target-duration" value="30" min="5" max="180">
    </div>
    <button id="generate-btn" class="submit-btn" disabled>
      <span>Generate Soundtrack</span><i class="fa-solid fa-wand-magic-sparkles"></i>
    </button>
  </section>

  <section class="glass-panel hidden" id="loading-section">
    <div class="loader"><div class="waveform">
      <div class="bar"></div><div class="bar"></div><div class="bar"></div>
      <div class="bar"></div><div class="bar"></div>
    </div></div>
    <h2>Composing Magic...</h2>
    <p id="loading-status">Analyzing video structure &amp; extracting vocals...</p>
    <div class="progress-container"><div class="progress-bar" id="progress-bar"></div></div>
  </section>

  <section class="glass-panel hidden" id="result-section">
    <h2><i class="fa-solid fa-circle-check" style="color:#4ade80;"></i> Composition Complete!</h2>
    <div class="video-container"><video id="output-video" controls autoplay></video></div>
    <div class="action-buttons">
      <a id="download-btn" href="#" download class="btn-secondary"><i class="fa-solid fa-download"></i> Download</a>
      <button id="reset-btn" class="btn-primary"><i class="fa-solid fa-rotate-left"></i> Create Another</button>
    </div>
  </section>
</main>
<script>
const token = localStorage.getItem('synthaverse_token');
if (!token) {{ window.location.href = '/login'; }}

fetch('/api/auth/me', {{headers:{{'Authorization':'Bearer '+token}}}})
  .then(r=>{{if(!r.ok)throw new Error();return r.json();}})
  .then(d=>{{
    document.getElementById('user-nav').style.display='block';
    document.getElementById('username-display').innerText=d.username;
    if(d.role==='admin') document.getElementById('admin-link').style.display='inline-flex';
  }}).catch(()=>{{localStorage.removeItem('synthaverse_token');window.location.href='/login';}});

window.logout=()=>{{localStorage.removeItem('synthaverse_token');window.location.href='/login';}};

const dropZone=document.getElementById('drop-zone');
const fileInput=document.getElementById('video-upload');
const fileInfo=document.getElementById('file-info');
const generateBtn=document.getElementById('generate-btn');
const uploadSection=document.getElementById('upload-section');
const loadingSection=document.getElementById('loading-section');
const resultSection=document.getElementById('result-section');
const loadingStatus=document.getElementById('loading-status');
const outputVideo=document.getElementById('output-video');
const downloadBtn=document.getElementById('download-btn');
const resetBtn=document.getElementById('reset-btn');
let selectedFile=null;

['dragenter','dragover','dragleave','drop'].forEach(e=>dropZone.addEventListener(e,ev=>{{ev.preventDefault();ev.stopPropagation();}}));
['dragenter','dragover'].forEach(e=>dropZone.addEventListener(e,()=>dropZone.classList.add('dragover')));
['dragleave','drop'].forEach(e=>dropZone.addEventListener(e,()=>dropZone.classList.remove('dragover')));
dropZone.addEventListener('drop',e=>handleFiles(e.dataTransfer.files));
fileInput.addEventListener('change',e=>handleFiles(e.target.files));

function handleFiles(files){{
  if(!files.length)return;
  const f=files[0];
  if(!f.type.startsWith('video/')){{alert('Please upload a video file.');return;}}
  selectedFile=f;
  fileInfo.textContent='Selected: '+f.name+' ('+(f.size/1024/1024).toFixed(2)+' MB)';
  generateBtn.disabled=false;
}}

function showSection(s){{
  [uploadSection,loadingSection,resultSection].forEach(x=>x.classList.add('hidden'));
  s.classList.remove('hidden');
}}

generateBtn.addEventListener('click',async()=>{{
  if(!selectedFile)return;
  showSection(loadingSection);
  const msgs=['Analyzing visual rhythm...','Matching BPM to scene cuts...','Generating AI instruments...','Mixing final audio stems...','Rendering final composition...'];
  let mi=0;
  const msgInt=setInterval(()=>{{mi=(mi+1)%msgs.length;loadingStatus.textContent=msgs[mi];}},5000);
  try{{
    const fd=new FormData();
    fd.append('video',selectedFile);
    fd.append('duration',document.getElementById('target-duration').value||30);
    const res=await fetch('/api/generate',{{method:'POST',headers:{{'Authorization':'Bearer '+token}},body:fd}});
    if(!res.ok){{clearInterval(msgInt);const e=await res.json();throw new Error(e.detail||'Server error');}}
    const data=await res.json();
    const pollInt=setInterval(async()=>{{
      try{{
        const sr=await fetch('/api/jobs/'+data.job_id,{{headers:{{'Authorization':'Bearer '+token}}}});
        if(!sr.ok)throw new Error('Status check failed');
        const jd=await sr.json();
        if(jd.status==='completed'){{
          clearInterval(pollInt);clearInterval(msgInt);
          outputVideo.src=jd.video_url;downloadBtn.href=jd.video_url;
          showSection(resultSection);outputVideo.load();
        }} else if(jd.status==='failed'){{
          clearInterval(pollInt);clearInterval(msgInt);
          throw new Error(jd.error||'Pipeline failed');
        }}
      }}catch(e){{clearInterval(pollInt);clearInterval(msgInt);alert('Error: '+e.message);showSection(uploadSection);}}
    }},3000);
  }}catch(e){{clearInterval(msgInt);alert('Error: '+e.message);showSection(uploadSection);}}
}});

resetBtn.addEventListener('click',()=>{{
  selectedFile=null;fileInput.value='';fileInfo.textContent='No file selected';
  generateBtn.disabled=true;outputVideo.src='';showSection(uploadSection);
}});
</script></body></html>"""

LOGIN_HTML = f"""<!DOCTYPE html><html lang="en"><head><title>Login - SynthaVerse</title>{_HEAD}</head>
<body>{_ORBS}
<main class="container">
  <header>
    <div class="logo"><i class="fa-solid fa-lock"></i><h1>Syntha<span>Login</span></h1></div>
    <p class="subtitle">Access the AI Composer</p>
  </header>
  <section class="glass-panel">
    <div class="auth-form" id="login-form">
      <div class="settings-group"><label>Username</label>
        <input type="text" id="username" required placeholder="Enter username"></div>
      <div class="settings-group"><label>Password</label>
        <input type="password" id="password" required placeholder="Enter password"></div>
      <p id="error-message" class="error-msg"></p>
      <button class="submit-btn" id="login-btn" onclick="doLogin()">
        <span>Log In</span><i class="fa-solid fa-arrow-right-to-bracket"></i>
      </button>
    </div>
    <div style="text-align:center;margin-top:2rem;">
      <p style="color:var(--text-secondary);">Don't have an account?
        <a href="/signup" style="color:var(--accent);text-decoration:none;font-weight:600;">Sign up here</a></p>
    </div>
  </section>
</main>
<script>
document.addEventListener('keydown',e=>{{if(e.key==='Enter')doLogin();}});
async function doLogin(){{
  const btn=document.getElementById('login-btn');
  btn.disabled=true;btn.innerHTML='<i class="fa-solid fa-spinner fa-spin"></i>';
  const fd=new FormData();
  fd.append('username',document.getElementById('username').value);
  fd.append('password',document.getElementById('password').value);
  try{{
    const res=await fetch('/api/auth/login',{{method:'POST',body:fd}});
    const data=await res.json();
    if(!res.ok)throw new Error(data.detail||'Login failed');
    localStorage.setItem('synthaverse_token',data.access_token);
    window.location.href='/';
  }}catch(err){{
    document.getElementById('error-message').innerText=err.message;
  }}finally{{
    btn.disabled=false;btn.innerHTML='<span>Log In</span><i class="fa-solid fa-arrow-right-to-bracket"></i>';
  }}
}}
</script></body></html>"""

SIGNUP_HTML = f"""<!DOCTYPE html><html lang="en"><head><title>Sign Up - SynthaVerse</title>{_HEAD}</head>
<body>{_ORBS}
<main class="container">
  <header>
    <div class="logo"><i class="fa-solid fa-user-plus"></i><h1>Syntha<span>Verse</span></h1></div>
    <p class="subtitle">Join the AI Music Revolution</p>
  </header>
  <section class="glass-panel">
    <div class="auth-form" id="signup-form">
      <div class="settings-group"><label>Username</label>
        <input type="text" id="username" required placeholder="Choose a username"></div>
      <div class="settings-group"><label>Email Address</label>
        <input type="email" id="email" required placeholder="Enter your email"></div>
      <div class="settings-group"><label>Password</label>
        <input type="password" id="password" required minlength="6" placeholder="Create a strong password"></div>
      <p id="error-message" class="error-msg"></p>
      <button class="submit-btn" id="signup-btn" onclick="doSignup()">
        <span>Create Account</span><i class="fa-solid fa-wand-magic-sparkles"></i>
      </button>
    </div>
    <div class="auth-form hidden" id="otp-form">
      <h3 style="text-align:center;color:white;">Email Verification</h3>
      <p style="text-align:center;color:var(--text-secondary);font-size:.9rem;">We sent a 6-digit code to your email.</p>
      <div class="settings-group"><label>OTP Code</label>
        <input type="text" id="otp" required maxlength="6" placeholder="123456"
          style="text-align:center;font-size:1.5rem;letter-spacing:5px;"></div>
      <p id="otp-error-message" class="error-msg"></p>
      <button class="submit-btn" id="otp-btn" onclick="doVerify()">
        <span>Verify Account</span><i class="fa-solid fa-check-circle"></i>
      </button>
    </div>
    <div style="text-align:center;margin-top:2rem;">
      <p style="color:var(--text-secondary);">Already have an account?
        <a href="/login" style="color:var(--accent);text-decoration:none;font-weight:600;">Log in here</a></p>
    </div>
  </section>
</main>
<script>
async function doSignup(){{
  const btn=document.getElementById('signup-btn');
  btn.disabled=true;btn.innerHTML='<i class="fa-solid fa-spinner fa-spin"></i>';
  try{{
    const res=await fetch('/api/auth/signup',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{
        username:document.getElementById('username').value,
        email:document.getElementById('email').value,
        password:document.getElementById('password').value
      }})}});
    const data=await res.json();
    if(!res.ok)throw new Error(data.detail||'Signup failed');
    document.getElementById('signup-form').classList.add('hidden');
    document.getElementById('otp-form').classList.remove('hidden');
  }}catch(err){{document.getElementById('error-message').innerText=err.message;}}
  finally{{btn.disabled=false;btn.innerHTML='<span>Create Account</span><i class="fa-solid fa-wand-magic-sparkles"></i>';}}
}}
async function doVerify(){{
  const btn=document.getElementById('otp-btn');
  btn.disabled=true;btn.innerHTML='<i class="fa-solid fa-spinner fa-spin"></i>';
  try{{
    const res=await fetch('/api/auth/verify-otp',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{
        username:document.getElementById('username').value,
        otp:document.getElementById('otp').value
      }})}});
    const data=await res.json();
    if(!res.ok)throw new Error(data.detail||'Verification failed');
    localStorage.setItem('synthaverse_token',data.access_token);
    window.location.href='/';
  }}catch(err){{document.getElementById('otp-error-message').innerText=err.message;}}
  finally{{btn.disabled=false;btn.innerHTML='<span>Verify Account</span><i class="fa-solid fa-check-circle"></i>';}}
}}
</script></body></html>"""

ADMIN_HTML = f"""<!DOCTYPE html><html lang="en"><head><title>Admin - SynthaVerse</title>{_HEAD}</head>
<body>{_ORBS}
<main class="container" style="max-width:800px;">
  <header style="display:flex;justify-content:space-between;align-items:center;">
    <div class="logo"><i class="fa-solid fa-shield-halved"></i><h1>Syntha<span>Admin</span></h1></div>
    <a href="/" class="btn-secondary" style="text-decoration:none;"><i class="fa-solid fa-house"></i> Home</a>
  </header>
  <section class="glass-panel">
    <h2><i class="fa-solid fa-users"></i> Registered Users</h2>
    <p style="color:var(--text-secondary);margin-bottom:1rem;">All active connections to your AI Composer Node.</p>
    <p id="error-message" style="color:#f87171;text-align:center;"></p>
    <table class="table-container" id="users-table">
      <thead><tr><th>ID</th><th>Username</th><th>Email</th><th>Status</th><th>Role</th></tr></thead>
      <tbody id="user-rows"><tr><td colspan="5" style="text-align:center;">Loading...</td></tr></tbody>
    </table>
  </section>
</main>
<script>
(async()=>{{
  const token=localStorage.getItem('synthaverse_token');
  if(!token){{window.location.href='/login';return;}}
  try{{
    const res=await fetch('/api/auth/admin/users',{{headers:{{'Authorization':'Bearer '+token}}}});
    if(res.status===401||res.status===403){{alert('Unauthorized!');window.location.href='/';return;}}
    if(!res.ok)throw new Error('Could not load users');
    const users=await res.json();
    const tbody=document.getElementById('user-rows');
    tbody.innerHTML='';
    if(!users.length){{tbody.innerHTML='<tr><td colspan="5" style="text-align:center;color:gray;">No users registered</td></tr>';return;}}
    users.forEach(u=>{{
      const row=document.createElement('tr');
      const rc=u.role==='admin'?'role-badge role-admin':'role-badge';
      const st=u.is_verified?"<span style='color:#4ade80;'>✓ Verified</span>":"<span style='color:#f87171;'>⏳ Pending</span>";
      row.innerHTML='<td style="color:gray;">#'+u.id+'</td><td style="font-weight:bold;">'+u.username+'</td><td style="color:#cbd5e1;">'+u.email+'</td><td>'+st+'</td><td><span class="'+rc+'">'+u.role+'</span></td>';
      tbody.appendChild(row);
    }});
  }}catch(e){{document.getElementById('error-message').innerText=e.message;}}
}})();
</script></body></html>"""


def _serve_static(filename: str):
    path = os.path.join(STATIC_DIR, filename)
    if os.path.exists(path):
        return FileResponse(path)
    pages = {
        "index.html": INDEX_HTML, "login.html": LOGIN_HTML,
        "signup.html": SIGNUP_HTML, "admin.html": ADMIN_HTML,
    }
    if filename in pages:
        return HTMLResponse(content=pages[filename])
    raise HTTPException(status_code=404, detail=f"{filename} not found")


# ===========================================================================
# Queue worker & app setup
# ===========================================================================
async def process_queue_worker():
    logger.info("Initializing Sequential Video Queue Worker...")
    while True:
        db = SessionLocal()
        job = None
        temp_video_path = None
        try:
            job = db.query(VideoJob).filter(VideoJob.status == "pending").first()
            if not job:
                await asyncio.sleep(3)
                continue
            job.status = "processing"
            db.commit()
            job_id = job.id
            temp_video_path = job.input_path
            duration = job.duration
            logger.info(f"Worker picked up job {job_id}.")
            final_video_path = await asyncio.to_thread(
                run_agent, input_video=temp_video_path, target_duration=duration
            )
            if not final_video_path or not os.path.exists(final_video_path):
                raise Exception("Agent pipeline failed to produce a final video.")
            file_name = os.path.basename(final_video_path)
            job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
            job.status = "completed"
            job.video_url = f"/api/output/{file_name}"
            db.commit()
            logger.info(f"Job {job_id} finished successfully.")
        except Exception as e:
            logger.error(f"Worker job error: {str(e)}")
            if job is not None:
                try:
                    job = db.query(VideoJob).filter(VideoJob.id == job.id).first()
                    if job:
                        job.status = "failed"
                        job.error = str(e)
                        db.commit()
                except Exception as ie:
                    logger.error(f"Worker failed to save error state: {ie}")
        finally:
            if temp_video_path and os.path.exists(temp_video_path):
                try:
                    os.remove(temp_video_path)
                except Exception:
                    pass
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker_task = asyncio.create_task(process_queue_worker())
    logger.info("Queue worker started.")
    yield
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    logger.info("Queue worker stopped.")


_raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app = FastAPI(title="AI Music Composer API", version="1.0", lifespan=lifespan)
app.include_router(auth_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount /static only if there are real files (CSS, JS assets etc.)
_has_static = os.path.exists(STATIC_DIR) and any(True for _ in os.scandir(STATIC_DIR))
if _has_static:
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def serve_frontend():
    return _serve_static("index.html")

@app.get("/login")
async def serve_login():
    return _serve_static("login.html")

@app.get("/signup")
async def serve_signup():
    return _serve_static("signup.html")

@app.get("/admin")
async def serve_admin():
    return _serve_static("admin.html")


@app.post("/api/generate")
async def generate_music(
    video: UploadFile = File(...),
    duration: int = Form(30),
    current_user=Depends(get_current_user)
):
    if not video.filename:
        raise HTTPException(status_code=400, detail="No video file provided.")
    logger.info(f"Upload: {video.filename} duration={duration}s user={current_user.username}")
    file_id = str(uuid.uuid4())
    _, ext = os.path.splitext(video.filename)
    ext = ext if ext else ".mp4"
    temp_video_path = os.path.join(UPLOAD_DIR, f"upload_{file_id}{ext}")
    try:
        with open(temp_video_path, "wb") as buffer:
            shutil.copyfileobj(video.file, buffer)
        db = SessionLocal()
        try:
            db.add(VideoJob(id=file_id, status="pending", input_path=temp_video_path, duration=duration))
            db.commit()
        finally:
            db.close()
        return JSONResponse(status_code=202, content={
            "status": "pending", "message": "Video queued.", "job_id": file_id
        })
    except Exception as e:
        logger.error(f"Ingest error: {str(e)}")
        if os.path.exists(temp_video_path):
            os.remove(temp_video_path)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str, current_user=Depends(get_current_user)):
    db = SessionLocal()
    try:
        job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return JSONResponse(content={"id": job.id, "status": job.status,
                                     "video_url": job.video_url, "error": job.error})
    finally:
        db.close()


@app.get("/api/output/{filename}")
async def get_output_video(filename: str, current_user=Depends(get_current_user)):
    safe_name = os.path.basename(filename)
    file_path = os.path.join("output", safe_name)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="video/mp4")
    raise HTTPException(status_code=404, detail="File not found")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
