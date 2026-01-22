"""Main application entry point with FastAPI and Slack bot integration."""

import logging
import signal
import sys
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import ValidationError

from .config import get_settings
from .database import check_database_health, dispose_engine
from .slack_handler import start_slack_bot, stop_slack_bot

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global reference to Slack bot thread
slack_thread: threading.Thread | None = None


def validate_environment():
    """Validate all required environment variables on startup."""
    try:
        settings = get_settings()
        logger.info("Environment variables validated successfully")
        return settings
    except ValidationError as e:
        logger.error("ERROR: Missing or invalid environment variables:")
        logger.error(str(e))
        sys.exit(1)


def start_slack_bot_thread():
    """Start Slack bot in a background thread."""
    global slack_thread
    slack_thread = threading.Thread(target=start_slack_bot, daemon=True)
    slack_thread.start()
    logger.info("Slack bot started in background thread")


def shutdown_handler(sig, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {sig}, shutting down gracefully...")

    # Stop Slack bot
    stop_slack_bot()

    # Dispose database connections
    dispose_engine()

    logger.info("Shutdown complete")
    sys.exit(0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown."""
    # Startup
    logger.info("Starting Grocery Assistant...")

    # Validate environment
    validate_environment()

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # Start Slack bot in background
    start_slack_bot_thread()

    logger.info("Grocery Assistant started successfully")

    yield

    # Shutdown
    logger.info("Shutting down Grocery Assistant...")
    stop_slack_bot()
    dispose_engine()
    logger.info("Grocery Assistant shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Grocery Assistant",
    description="A conversational grocery shopping assistant",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    """Health check endpoint for Railway.

    Verifies database connection and returns status.
    """
    db_healthy = check_database_health()

    if db_healthy:
        return {
            "status": "healthy",
            "database": "connected",
        }
    else:
        return {
            "status": "unhealthy",
            "database": "disconnected",
        }


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Grocery Assistant",
        "status": "running",
        "version": "1.0.0",
    }
