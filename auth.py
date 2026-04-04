import os
import random
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import bcrypt
import jwt
from pydantic import BaseModel

from database import User, get_db

# -----------------
# Security Settings
# -----------------
SECRET_KEY = os.getenv("JWT_SECRET_KEY")

if not SECRET_KEY:
    # On Hugging Face Spaces, always require the secret to be set via Space Secrets.
    # Generate a random one per-process as a last resort so the app doesn't crash,
    # but log a very loud warning — tokens will be invalidated on every restart.
    import secrets as _secrets
    SECRET_KEY = _secrets.token_hex(32)
    print(
        "\n\n=== SECURITY WARNING =========================\n"
        "JWT_SECRET_KEY environment variable is not set!\n"
        "A random key has been generated for this session.\n"
        "All user sessions will be invalidated on every restart.\n"
        "Set JWT_SECRET_KEY in your HF Space Secrets to fix this.\n"
        "=============================================\n\n"
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days before force-logout

# OAuth2 native specification, tells FastAPI where the login post route lives
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8")
    )


def get_password_hash(password: str) -> str:
    """Hash a password with bcrypt and return the hash string."""
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def send_otp_email(to_email: str, otp: str):
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")

    if not smtp_username or not smtp_password:
        print(f"Warning: SMTP not configured. OTP for {to_email} is {otp}")
        return

    msg = EmailMessage()
    msg.set_content(
        f"Your SynthaVerse verification OTP is: {otp}\n\nThis code will expire shortly."
    )
    msg["Subject"] = "SynthaVerse Registration OTP"
    msg["From"] = smtp_username
    msg["To"] = to_email

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print(f"Error sending email: {e}")


# -----------------
# Dependencies
# -----------------
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    """Validates the JWT token across protected API routes."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials. Please log in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user


async def get_current_admin(current_user: User = Depends(get_current_user)):
    """Blocks anyone without the global 'admin' SQL role."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have administrative dashboard privileges."
        )
    return current_user


# -----------------
# Pydantic Schemas
# -----------------
class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    # SECURITY FIX: Admin backdoor via signup payload has been removed entirely.
    # Admin role is now only granted via the ADMIN_EMAIL environment variable
    # after OTP verification, or by manually updating the database.


class OTPVerify(BaseModel):
    username: str
    otp: str


# -----------------
# API Routing
# -----------------
@router.post("/signup")
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    """Saves a new user to the SQLite Database and sends OTP."""
    db_user = db.query(User).filter(
        (User.username == user.username) | (User.email == user.email)
    ).first()
    if db_user:
        raise HTTPException(
            status_code=400,
            detail="Username or email already registered, pick another."
        )

    hashed_pwd = get_password_hash(user.password)
    otp_code = str(random.randint(100000, 999999))

    new_user = User(
        username=user.username,
        email=user.email,
        hashed_password=hashed_pwd,
        role="user",           # All new users start as regular users
        is_verified=0,
        otp=otp_code
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    send_otp_email(user.email, otp_code)
    return {"message": "OTP sent to email. Please verify."}


@router.post("/verify-otp")
def verify_otp(data: OTPVerify, db: Session = Depends(get_db)):
    """Verifies the OTP and activates the user."""
    user = db.query(User).filter(User.username == data.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if user.is_verified:
        raise HTTPException(status_code=400, detail="User already verified.")

    if user.otp != data.otp:
        raise HTTPException(status_code=401, detail="Invalid OTP.")

    # Grant admin role if the verified email matches the ADMIN_EMAIL secret
    admin_email = os.getenv("ADMIN_EMAIL", "")
    if admin_email and user.email.lower() == admin_email.lower():
        user.role = "admin"

    user.is_verified = 1
    user.otp = None
    db.commit()

    access_token = create_access_token(
        data={"sub": user.username, "role": user.role},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "message": "Verification successful."
    }


@router.post("/login")
def login_route(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """Logs the user in by validating the form data and rendering a JWT."""
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password. Please try again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not verified. Please register or verify your OTP.",
        )

    access_token = create_access_token(
        data={"sub": user.username, "role": user.role},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": access_token, "token_type": "bearer", "role": user.role}


@router.get("/me")
def read_users_me(current_user: User = Depends(get_current_user)):
    """Returns the profile data attached to the current user's token."""
    return {"username": current_user.username, "role": current_user.role}


@router.get("/admin/users")
def get_all_users(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """A heavily guarded endpoint that returns all registered users."""
    users = db.query(User).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "role": u.role,
            "is_verified": bool(u.is_verified)
        }
        for u in users
    ]
