"""Claude API integration and context building."""

import logging
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic
from sqlalchemy.orm import Session

from .config import get_settings
from .models import (
    ShoppingList,
    ShoppingListStatus,
    BrandPreference,
    Conversation,
    RecipeNote,
    normalize_recipe_name,
)

logger = logging.getLogger(__name__)

# Initialize Anthropic client
settings = get_settings()
client = Anthropic(api_key=settings.anthropic_api_key)

# Path to system prompt
SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system_prompt.txt"


def load_system_prompt() -> str:
    """Load the system prompt from file."""
    with open(SYSTEM_PROMPT_PATH, "r") as f:
        return f.read()


def get_active_list_items(db_session: Session) -> list[dict]:
    """Get items from the current active shopping list."""
    active_list = (
        db_session.query(ShoppingList)
        .filter(ShoppingList.status == ShoppingListStatus.ACTIVE)
        .first()
    )
    if active_list and active_list.items:
        return active_list.items
    return []


def get_all_brand_preferences(db_session: Session) -> list[dict]:
    """Get all brand preferences."""
    prefs = db_session.query(BrandPreference).all()
    return [
        {
            "item": p.generic_item,
            "brand": p.preferred_brand,
            "confidence": p.confidence.value,
        }
        for p in prefs
    ]


def get_brand_preference(item_name: str, db_session: Session) -> dict | None:
    """Get brand preference for a specific item.

    Args:
        item_name: The generic item name to look up.
        db_session: Database session.

    Returns:
        Dict with item, brand, confidence if found, None otherwise.
    """
    # Normalize to lowercase for matching
    normalized_item = item_name.strip().lower()
    pref = (
        db_session.query(BrandPreference)
        .filter(BrandPreference.generic_item == normalized_item)
        .first()
    )
    if pref:
        return {
            "item": pref.generic_item,
            "brand": pref.preferred_brand,
            "confidence": pref.confidence.value,
        }
    return None


def get_order_history(db_session: Session, limit: int = 5) -> list[dict]:
    """Get recent ordered lists for reference.

    Args:
        db_session: Database session.
        limit: Maximum number of orders to return.

    Returns:
        List of ordered shopping lists with items and metadata.
    """
    orders = (
        db_session.query(ShoppingList)
        .filter(ShoppingList.status == ShoppingListStatus.ORDERED)
        .order_by(ShoppingList.ordered_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": o.id,
            "items": o.items,
            "item_count": len(o.items) if o.items else 0,
            "ordered_at": o.ordered_at.isoformat() if o.ordered_at else None,
        }
        for o in orders
    ]


def get_recent_messages(db_session: Session, limit: int = 5) -> list[dict]:
    """Get recent conversation messages for context."""
    messages = (
        db_session.query(Conversation)
        .order_by(Conversation.timestamp.desc())
        .limit(limit)
        .all()
    )
    # Reverse to get chronological order
    messages = list(reversed(messages))
    return [
        {
            "user": m.user,
            "message": m.message,
            "response": m.response,
            "timestamp": m.timestamp.isoformat() if m.timestamp else None,
        }
        for m in messages
    ]


def get_recent_notes(db_session: Session, limit: int = 10) -> list[dict]:
    """Get recent recipe notes for context."""
    notes = (
        db_session.query(RecipeNote)
        .order_by(RecipeNote.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "recipe_name": n.recipe_name,
            "user": n.user,
            "note_text": n.note_text,
            "note_type": n.note_type.value,
            "outcome": n.outcome.value,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notes
    ]


def get_notes_for_recipe(recipe_name: str, db_session: Session) -> list[dict]:
    """Get all notes for a specific recipe (case-insensitive matching).

    Args:
        recipe_name: The recipe name to search for.
        db_session: Database session.

    Returns:
        List of note dicts for the recipe, ordered by most recent first.
    """
    normalized = normalize_recipe_name(recipe_name)
    notes = (
        db_session.query(RecipeNote)
        .filter(RecipeNote.recipe_name_normalized == normalized)
        .order_by(RecipeNote.created_at.desc())
        .all()
    )
    return [
        {
            "recipe_name": n.recipe_name,
            "user": n.user,
            "note_text": n.note_text,
            "note_type": n.note_type.value,
            "outcome": n.outcome.value,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notes
    ]


def build_context(user: str, db_session: Session) -> dict:
    """Build context packet for Claude API call with size limits."""
    shopping_list = get_active_list_items(db_session)

    # Truncate large lists to prevent context overflow
    truncated = False
    original_count = len(shopping_list)
    if len(shopping_list) > 50:
        shopping_list = shopping_list[:50]
        truncated = True

    brand_preferences = get_all_brand_preferences(db_session)
    recent_messages = get_recent_messages(db_session, limit=5)
    recent_notes = get_recent_notes(db_session, limit=10)

    return {
        "today": datetime.now().isoformat(),
        "user_asking": user,
        "current_shopping_list": shopping_list,
        "shopping_list_truncated": truncated,
        "shopping_list_total_count": original_count,
        "brand_preferences": brand_preferences,
        "recent_messages": recent_messages,
        "recent_recipe_notes": recent_notes,
    }


def format_shopping_list(items: list[dict], truncated: bool = False, total_count: int = 0) -> str:
    """Format shopping list items for Claude context."""
    if not items:
        return "(empty)"

    lines = []
    for item in items:
        parts = [f"- {item.get('name', 'Unknown')}"]
        if item.get("quantity") and item.get("unit"):
            parts.append(f"({item['quantity']} {item['unit']})")
        elif item.get("quantity"):
            parts.append(f"({item['quantity']})")
        if item.get("brand"):
            parts.append(f"[{item['brand']}]")
        if item.get("added_by"):
            parts.append(f"(added by {item['added_by']})")
        lines.append(" ".join(parts))

    if truncated:
        lines.append(f"... and {total_count - len(items)} more items (list truncated)")

    return "\n".join(lines)


def format_brand_preferences(prefs: list[dict]) -> str:
    """Format brand preferences for Claude context."""
    if not prefs:
        return "(none set)"

    lines = []
    for p in prefs:
        conf = f" [{p['confidence']}]" if p.get("confidence") else ""
        lines.append(f"- {p['item']} -> {p['brand']}{conf}")
    return "\n".join(lines)


def format_recent_messages(messages: list[dict]) -> str:
    """Format recent messages for Claude context."""
    if not messages:
        return "(no recent messages)"

    lines = []
    for m in messages:
        lines.append(f"{m['user']}: {m['message']}")
        if m.get("response"):
            # Truncate long responses
            response = m["response"]
            if len(response) > 200:
                response = response[:200] + "..."
            lines.append(f"Assistant: {response}")
    return "\n".join(lines)


def format_recipe_notes(notes: list[dict]) -> str:
    """Format recipe notes for Claude context."""
    if not notes:
        return "(no recipe notes)"

    lines = []
    for n in notes:
        outcome_indicator = {
            "better": "+",
            "worse": "-",
            "neutral": "~",
        }.get(n.get("outcome", "neutral"), "~")

        lines.append(
            f"- [{outcome_indicator}] {n['recipe_name']} ({n['user']}): {n['note_text']}"
        )
    return "\n".join(lines)


def format_context_for_claude(context: dict) -> str:
    """Format context as readable text for Claude."""
    shopping_list_str = format_shopping_list(
        context["current_shopping_list"],
        context.get("shopping_list_truncated", False),
        context.get("shopping_list_total_count", 0),
    )

    return f"""=== CURRENT CONTEXT ===

TODAY: {context['today']}
USER: {context['user_asking']}

CURRENT SHOPPING LIST ({len(context['current_shopping_list'])} items):
{shopping_list_str}

BRAND PREFERENCES:
{format_brand_preferences(context['brand_preferences'])}

RECENT CONVERSATION:
{format_recent_messages(context['recent_messages'])}

RECENT RECIPE NOTES:
{format_recipe_notes(context['recent_recipe_notes'])}

=== USER MESSAGE ==="""


def build_context_snapshot(context: dict, input_tokens: int, output_tokens: int) -> dict:
    """Build context snapshot for logging to conversations table."""
    return {
        "shopping_list_size": len(context["current_shopping_list"]),
        "brand_prefs_count": len(context["brand_preferences"]),
        "recent_messages_count": len(context["recent_messages"]),
        "recent_notes_count": len(context["recent_recipe_notes"]),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def get_claude_response(
    user_message: str, user: str, db_session: Session
) -> tuple[str, dict, dict]:
    """Call Claude API with context and return (response_text, metadata, context).

    Args:
        user_message: The user's message text.
        user: Display name ("Erich" or "L").
        db_session: Database session.

    Returns:
        Tuple of (response_text, metadata, context) where:
        - response_text: Raw response from Claude
        - metadata: Dict with input_tokens, output_tokens, model
        - context: The context dict that was sent to Claude

    Raises:
        Exception: If Claude API call fails.
    """
    context = build_context(user, db_session)
    system_prompt = load_system_prompt()

    formatted_context = format_context_for_claude(context)
    full_message = f"{formatted_context}\n\n{user_message}"

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            timeout=30.0,  # 30 second timeout
            system=system_prompt,
            messages=[{"role": "user", "content": full_message}],
        )

        # Extract usage for logging
        metadata = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "model": response.model,
        }

        response_text = response.content[0].text

        logger.info(
            f"Claude response: {metadata['input_tokens']} in, {metadata['output_tokens']} out"
        )

        return response_text, metadata, context

    except Exception as e:
        logger.exception(f"Claude API error: {e}")
        raise
