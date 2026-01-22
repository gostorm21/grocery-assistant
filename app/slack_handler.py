"""Slack bot event handlers using Slack Bolt."""

import logging
from datetime import datetime

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from .config import get_settings
from .database import get_db_session
from .models import Conversation, ConversationStatus
from .claude_service import get_claude_response, build_context_snapshot
from .action_parser import process_claude_response, get_or_create_active_list

logger = logging.getLogger(__name__)

# Initialize settings
settings = get_settings()

# Initialize Slack Bolt app
slack_app = App(token=settings.slack_bot_token)


def get_user_name(slack_user_id: str) -> str | None:
    """Map Slack user ID to display name.

    Returns:
        "Erich" or "L" if known user, None if unknown.
    """
    return settings.user_mapping.get(slack_user_id)


def process_message(message_text: str, user_name: str, slack_user_id: str, message_ts: str) -> str:
    """Process a message and return the response.

    This function:
    1. Gets a database session
    2. Gets the active shopping list ID for logging
    3. Calls Claude API with context
    4. Parses response and executes actions
    5. Logs the conversation to the database
    6. Returns the natural language response

    Args:
        message_text: The user's message text.
        user_name: Display name ("Erich" or "L").
        slack_user_id: Raw Slack user ID.
        message_ts: Slack message timestamp for linking.

    Returns:
        Response text to send back to the channel.
    """
    with get_db_session() as db_session:
        # Get active shopping list ID for logging
        active_list = get_or_create_active_list(db_session)
        shopping_list_id = active_list.id

        # Initialize variables for logging
        response_text = None
        status = ConversationStatus.SUCCESS
        assistant_model = None
        context_snapshot = None

        try:
            # Call Claude API
            raw_response, metadata, context = get_claude_response(
                message_text, user_name, db_session
            )

            # Extract metadata for logging
            assistant_model = metadata.get("model")
            context_snapshot = build_context_snapshot(
                context,
                metadata.get("input_tokens", 0),
                metadata.get("output_tokens", 0),
            )

            # Parse response and execute actions
            try:
                response_text = process_claude_response(raw_response, db_session)
                status = ConversationStatus.SUCCESS
            except Exception as e:
                logger.exception(f"Error parsing/executing actions: {e}")
                status = ConversationStatus.PARSE_ERROR
                # Try to extract readable text from raw response
                from .action_parser import extract_text_fallback
                response_text = extract_text_fallback(raw_response)
                if not response_text:
                    response_text = "I understood your message but had trouble processing the action."
                # Store raw response in context_snapshot for debugging
                if context_snapshot:
                    context_snapshot["raw_response"] = raw_response

        except Exception as e:
            logger.exception(f"Claude API error: {e}")
            status = ConversationStatus.API_ERROR
            response_text = "Sorry, I'm having trouble thinking right now. Try again in a moment."
            # Create minimal context snapshot for error logging
            context_snapshot = {"error": str(e)}

        # Log conversation to database
        try:
            conversation = Conversation(
                shopping_list_id=shopping_list_id,
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
            # Don't fail the response if logging fails

        return response_text


@slack_app.event("message")
def handle_message(event, say, ack):
    """Handle incoming messages in the grocery channel.

    - Acknowledges immediately to prevent Slack timeout
    - Ignores bot messages to prevent loops
    - Ignores unknown users silently
    - Responds in main channel (not in thread)
    """
    # Acknowledge immediately (Slack expects response within 3 seconds)
    ack()

    # Ignore bot messages to prevent loops
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return

    # Only process messages in the configured channel
    if event.get("channel") != settings.slack_channel_id:
        return

    # Extract user info
    slack_user_id = event.get("user")
    if not slack_user_id:
        return

    # Ignore unknown users silently
    user_name = get_user_name(slack_user_id)
    if not user_name:
        return

    # Get message details
    message_text = event.get("text", "").strip()
    message_ts = event.get("ts", "")

    # Skip empty messages
    if not message_text:
        return

    # Process message and respond
    try:
        response = process_message(message_text, user_name, slack_user_id, message_ts)
        # Respond in main channel (not in thread)
        say(response)

    except Exception as e:
        logger.exception(f"Error processing message from {user_name}: {e}")
        say("Sorry, I'm having trouble right now. Try again in a moment.")


def create_socket_mode_handler() -> SocketModeHandler:
    """Create Socket Mode handler for the Slack app."""
    return SocketModeHandler(slack_app, settings.slack_app_token)


def start_slack_bot():
    """Start the Slack bot in Socket Mode.

    This is a blocking call - use in a separate thread.
    """
    handler = create_socket_mode_handler()
    handler.start()


def stop_slack_bot():
    """Stop the Slack bot gracefully."""
    # Socket Mode handler will stop when the process exits
    # Additional cleanup can be added here if needed
    pass
