"""Slack bot event handlers using Slack Bolt."""

import logging
from datetime import datetime

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from .config import get_settings
from .database import get_db_session
from .models import Conversation, ConversationStatus
from .claude_service import get_claude_response

logger = logging.getLogger(__name__)

# Initialize settings
settings = get_settings()

# Initialize Slack Bolt app
slack_app = App(token=settings.slack_bot_token)


def get_user_name(slack_user_id: str) -> str | None:
    """Map Slack user ID to display name.

    Returns:
        "Erich" or "Lauren" if known user, None if unknown.
    """
    return settings.user_mapping.get(slack_user_id)


def process_message(message_text: str, user_name: str, slack_user_id: str, message_ts: str) -> str:
    """Process a message through the agentic tool-use loop.

    1. Call get_claude_response() — runs the full agentic loop (tools execute inside)
    2. Log conversation with metadata
    3. Return response text
    """
    with get_db_session() as db_session:
        response_text = None
        status = ConversationStatus.SUCCESS
        assistant_model = None
        context_snapshot = None

        try:
            print(f"[PROCESS] {user_name}: {message_text[:100]}", flush=True)

            # Agentic loop — actions execute inside
            response_text, artifacts, metadata = get_claude_response(
                message_text, user_name, db_session
            )

            assistant_model = metadata.get("model")
            context_snapshot = {
                "input_tokens": metadata.get("input_tokens", 0),
                "output_tokens": metadata.get("output_tokens", 0),
                "turns": metadata.get("turns", 1),
            }

            if metadata.get("hit_limit"):
                context_snapshot["hit_limit"] = True
            if metadata.get("error"):
                context_snapshot["error"] = metadata["error"]

            print(
                f"[PROCESS] Response: {metadata.get('turns', 1)} turns, "
                f"{metadata.get('input_tokens', 0)} in, "
                f"{metadata.get('output_tokens', 0)} out",
                flush=True,
            )

        except Exception as e:
            logger.exception(f"Claude API error: {e}")
            print(f"[PROCESS] ERROR: {type(e).__name__}: {e}", flush=True)
            status = ConversationStatus.API_ERROR
            response_text = "Sorry, I'm having trouble thinking right now. Try again in a moment."
            context_snapshot = {"error": str(e)}

        # Log conversation
        try:
            conversation = Conversation(
                timestamp=datetime.utcnow(),
                user=user_name,
                message=message_text,
                response=response_text,
                status=status,
                slack_user_id=slack_user_id,
                slack_message_ts=message_ts,
                assistant_model=assistant_model,
                context_snapshot=context_snapshot,
            )
            db_session.add(conversation)
            db_session.commit()
        except Exception as e:
            logger.exception(f"Error logging conversation: {e}")

        return response_text


@slack_app.event("message")
def handle_message(event, say, ack):
    """Handle incoming messages in the grocery channel."""
    ack()

    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return

    if event.get("channel") != settings.slack_channel_id:
        return

    slack_user_id = event.get("user")
    if not slack_user_id:
        return

    user_name = get_user_name(slack_user_id)
    if not user_name:
        return

    message_text = event.get("text", "").strip()
    message_ts = event.get("ts", "")

    if not message_text:
        return

    try:
        response = process_message(message_text, user_name, slack_user_id, message_ts)
        say(response)
    except Exception as e:
        logger.exception(f"Error processing message from {user_name}: {e}")
        say("Sorry, I'm having trouble right now. Try again in a moment.")


def create_socket_mode_handler() -> SocketModeHandler:
    """Create Socket Mode handler for the Slack app."""
    return SocketModeHandler(slack_app, settings.slack_app_token)


def start_slack_bot():
    """Start the Slack bot in Socket Mode."""
    handler = create_socket_mode_handler()
    handler.start()


def stop_slack_bot():
    """Stop the Slack bot gracefully."""
    pass
