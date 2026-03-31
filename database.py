import os
from sqlalchemy import create_engine, Column, Integer, String, event
from sqlalchemy.orm import declarative_base, sessionmaker

# We will use a local SQLite file to act as our database to keep things free
DATABASE_URL = "sqlite:///./synthaverse.db"

# Create the SQLAlchemy engine
# connect_args is needed for SQLite to avoid thread-safety errors with FastAPI
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# Enable WAL (Write-Ahead Logging) mode on SQLite to allow concurrent reads and writes, 
# preventing 'database is locked' errors under heavy production load.
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_verified = Column(Integer, default=0) # SQLite uses 0/1 for boolean
    otp = Column(String, nullable=True)
    # Role differentiates normal users from the admin dashboard (e.g. "user" or "admin")
    role = Column(String, default="user")

class VideoJob(Base):
    __tablename__ = "generation_jobs"
    
    id = Column(String, primary_key=True, index=True) # UUID string
    status = Column(String, default="pending", index=True) # pending, processing, completed, failed
    input_path = Column(String, nullable=False)
    duration = Column(Integer, default=30)
    video_url = Column(String, nullable=True)
    error = Column(String, nullable=True)

# Automatically generate the tables upon import if they don't exist yet
Base.metadata.create_all(bind=engine)

def get_db():
    """Dependency for returning a per-request database session in FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
