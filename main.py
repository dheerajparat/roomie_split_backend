from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.db.session import engine, Base
import app.models  # Ensure all models are registered
from app.routers import auth, rooms, expenses, balances
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Automatically create tables in PostgreSQL
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8800",  "http://localhost:8800"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(rooms.router, prefix=settings.API_V1_STR)
app.include_router(expenses.router, prefix=settings.API_V1_STR)
app.include_router(balances.router, prefix=settings.API_V1_STR)

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": settings.PROJECT_NAME}

@app.get("/")
def root():
    return {
        "message": "Welcome to RoomieSplit API",
        "docs": "/docs",
        "version": settings.VERSION,
    }
