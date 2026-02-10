"""Claude API integration and context building."""

import json
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
    Recipe,
    MealPlan,
    MealPlanStatus,
    PantryItem,
    Preference,
    normalize_recipe_name,
)

logger = logging.getLogger(__name__)

# Initialize Anthropic client
settings = get_settings()
client = Anthropic(api_key=settings.anthropic_api_key)

# Path to system prompt
SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system_prompt.txt"
GROCERY_CLASSIFIER_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "grocery_classifier_prompt.txt"

# Default context sections (all enabled)
DEFAULT_SECTIONS = {
    "shopping_list": True,
    "brand_preferences": True,
    "recipes": True,
    "meal_plan": True,
    "pantry": True,
    "preferences": True,
    "recipe_notes": True,
    "order_history": True,
}


def load_system_prompt() -> str:
    """Load the system prompt from file."""
    with open(SYSTEM_PROMPT_PATH, "r") as f:
        return f.read()


def load_classifier_prompt() -> str:
    """Load the grocery classifier prompt from file."""
    with open(GROCERY_CLASSIFIER_PROMPT_PATH, "r") as f:
        return f.read()


# =============================================================================
# Haiku Classifier
# =============================================================================


def classify_grocery_message(user_message: str) -> dict:
    """Classify message with Haiku to determine which context sections to load.

    Returns default (all true) on error for graceful degradation.
    """
    try:
        classifier_prompt = load_classifier_prompt()

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            timeout=5.0,
            system=classifier_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        result_text = response.content[0].text.strip()
        parsed = json.loads(result_text)

        sections = parsed.get("context_sections", DEFAULT_SECTIONS)

        # Always force shopping_list and brand_preferences on
        sections["shopping_list"] = True
        sections["brand_preferences"] = True

        logger.info(f"Classifier sections: {sections}")
        return sections

    except Exception as e:
        logger.warning(f"Classifier failed, loading all sections: {e}")
        return dict(DEFAULT_SECTIONS)


# =============================================================================
# Data Retrieval Functions
# =============================================================================


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
            "kroger_product_id": p.kroger_product_id,
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
            "kroger_product_id": pref.kroger_product_id,
            "confidence": pref.confidence.value,
        }
    return None


def get_order_history(db_session: Session, limit: int = 5) -> list[dict]:
    """Get recent ordered lists for reference."""
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
    """Get all notes for a specific recipe (case-insensitive matching)."""
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


def get_known_recipes(db_session: Session, limit: int = 20) -> list[dict]:
    """Get saved recipes for context."""
    recipes = (
        db_session.query(Recipe)
        .order_by(Recipe.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "name": r.name,
            "ingredients": r.ingredients,
            "cuisine": r.cuisine,
            "tags": r.tags,
        }
        for r in recipes
    ]


def get_active_meal_plan(db_session: Session) -> dict | None:
    """Get the current active (PLANNING) meal plan."""
    plan = (
        db_session.query(MealPlan)
        .filter(MealPlan.status == MealPlanStatus.PLANNING)
        .order_by(MealPlan.created_at.desc())
        .first()
    )
    if plan:
        return {
            "id": plan.id,
            "meals": plan.meals or [],
            "status": plan.status.value,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
        }
    return None


def get_pantry_items(db_session: Session) -> list[dict]:
    """Get all pantry items."""
    items = db_session.query(PantryItem).order_by(PantryItem.item_name).all()
    return [
        {
            "item_name": i.item_name,
            "quantity": i.quantity,
            "unit": i.unit,
        }
        for i in items
    ]


def get_all_preferences(db_session: Session) -> list[dict]:
    """Get all user preferences."""
    prefs = db_session.query(Preference).all()
    return [
        {
            "user": p.user,
            "data": p.data or {},
        }
        for p in prefs
    ]


def get_kroger_status() -> dict:
    """Get Kroger integration status."""
    try:
        from .kroger_service import get_auth_status, is_configured
        return {
            "configured": is_configured(),
            "auth_status": get_auth_status(),
        }
    except Exception:
        return {
            "configured": False,
            "auth_status": "not_configured",
        }


# =============================================================================
# Context Building
# =============================================================================


def build_context(user: str, db_session: Session, user_message: str = None) -> dict:
    """Build context packet for Claude API call with size limits.

    Uses Haiku classifier to selectively load context sections when a
    user_message is provided.
    """
    # Classify to determine which sections to load
    if user_message:
        sections = classify_grocery_message(user_message)
    else:
        sections = dict(DEFAULT_SECTIONS)

    shopping_list = get_active_list_items(db_session)

    # Truncate large lists to prevent context overflow
    truncated = False
    original_count = len(shopping_list)
    if len(shopping_list) > 50:
        shopping_list = shopping_list[:50]
        truncated = True

    # Always loaded
    brand_preferences = get_all_brand_preferences(db_session)
    recent_messages = get_recent_messages(db_session, limit=5)

    # Conditionally loaded
    known_recipes = get_known_recipes(db_session) if sections.get("recipes") else []
    meal_plan = get_active_meal_plan(db_session) if sections.get("meal_plan") else None
    pantry_items = get_pantry_items(db_session) if sections.get("pantry") else []
    preferences = get_all_preferences(db_session) if sections.get("preferences") else []
    recent_notes = get_recent_notes(db_session, limit=10) if sections.get("recipe_notes") else []
    order_history = get_order_history(db_session) if sections.get("order_history") else []

    return {
        "today": datetime.now().isoformat(),
        "user_asking": user,
        "current_shopping_list": shopping_list,
        "shopping_list_truncated": truncated,
        "shopping_list_total_count": original_count,
        "brand_preferences": brand_preferences,
        "recent_messages": recent_messages,
        "known_recipes": known_recipes,
        "meal_plan": meal_plan,
        "pantry_items": pantry_items,
        "preferences": preferences,
        "recent_recipe_notes": recent_notes,
        "order_history": order_history,
        "kroger_status": get_kroger_status(),
        "classifier_sections": sections,
    }


# =============================================================================
# Formatting Functions
# =============================================================================


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
        # Kroger resolution status
        if item.get("kroger_product_id"):
            parts.append("[kroger: resolved]")
        elif item.get("brand"):
            parts.append("[kroger: needs resolution]")
        # Recipe source
        if item.get("from_recipe"):
            parts.append(f"(from: {item['from_recipe']})")
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
        kroger = f" (kroger: {p['kroger_product_id']})" if p.get("kroger_product_id") else ""
        lines.append(f"- {p['item']} -> {p['brand']}{conf}{kroger}")
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


def format_known_recipes(recipes: list[dict]) -> str:
    """Format saved recipes for Claude context."""
    if not recipes:
        return "(no saved recipes)"

    lines = []
    for r in recipes:
        parts = [f"- [#{r['id']}] {r['name']}"]
        if r.get("cuisine"):
            parts.append(f"({r['cuisine']})")
        if r.get("tags"):
            parts.append(f"[{', '.join(r['tags'])}]")
        if r.get("ingredients"):
            # Show ingredient count
            ing_list = r["ingredients"]
            if isinstance(ing_list, list):
                parts.append(f"({len(ing_list)} ingredients)")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def format_meal_plan(meal_plan: dict | None) -> str:
    """Format active meal plan for Claude context."""
    if not meal_plan:
        return "(no active meal plan)"

    meals = meal_plan.get("meals", [])
    if not meals:
        return "(meal plan started, no meals added yet)"

    lines = []
    for meal in meals:
        parts = [f"- {meal.get('meal_name', 'Unknown')}"]
        if meal.get("recipe_id"):
            parts.append(f"[recipe #{meal['recipe_id']}]")
        if meal.get("notes"):
            parts.append(f"— {meal['notes']}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def format_pantry(items: list[dict]) -> str:
    """Format pantry items for Claude context."""
    if not items:
        return "(pantry empty or not tracked)"

    lines = []
    for i in items:
        parts = [f"- {i['item_name']}"]
        if i.get("quantity") and i.get("unit"):
            parts.append(f"({i['quantity']} {i['unit']})")
        elif i.get("quantity"):
            parts.append(f"({i['quantity']})")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def format_preferences(prefs: list[dict]) -> str:
    """Format user preferences for Claude context."""
    if not prefs:
        return "(no preferences set)"

    lines = []
    for p in prefs:
        user = p["user"]
        data = p.get("data", {})
        for category, value in data.items():
            if isinstance(value, list):
                lines.append(f"- {user} — {category}: {', '.join(value)}")
            else:
                lines.append(f"- {user} — {category}: {value}")
    return "\n".join(lines) if lines else "(no preferences set)"


def format_order_history(orders: list[dict]) -> str:
    """Format order history for Claude context."""
    if not orders:
        return "(no order history)"

    lines = []
    for o in orders:
        date_str = o.get("ordered_at", "unknown date")
        lines.append(f"- Order #{o['id']} ({date_str}): {o['item_count']} items")
    return "\n".join(lines)


def format_context_for_claude(context: dict) -> str:
    """Format context as readable text for Claude."""
    shopping_list_str = format_shopping_list(
        context["current_shopping_list"],
        context.get("shopping_list_truncated", False),
        context.get("shopping_list_total_count", 0),
    )

    sections = [
        f"=== CURRENT CONTEXT ===",
        f"",
        f"TODAY: {context['today']}",
        f"USER: {context['user_asking']}",
        f"",
        f"CURRENT SHOPPING LIST ({len(context['current_shopping_list'])} items):",
        shopping_list_str,
        f"",
        f"BRAND PREFERENCES:",
        format_brand_preferences(context["brand_preferences"]),
        f"",
        f"RECENT CONVERSATION:",
        format_recent_messages(context["recent_messages"]),
    ]

    # Conditionally add sections
    if context.get("known_recipes"):
        sections.extend([
            f"",
            f"SAVED RECIPES ({len(context['known_recipes'])} recipes):",
            format_known_recipes(context["known_recipes"]),
        ])

    if context.get("meal_plan") is not None:
        sections.extend([
            f"",
            f"CURRENT MEAL PLAN:",
            format_meal_plan(context["meal_plan"]),
        ])

    if context.get("pantry_items"):
        sections.extend([
            f"",
            f"PANTRY (on hand):",
            format_pantry(context["pantry_items"]),
        ])

    if context.get("preferences"):
        sections.extend([
            f"",
            f"DIETARY PREFERENCES:",
            format_preferences(context["preferences"]),
        ])

    if context.get("recent_recipe_notes"):
        sections.extend([
            f"",
            f"RECENT RECIPE NOTES:",
            format_recipe_notes(context["recent_recipe_notes"]),
        ])

    if context.get("order_history"):
        sections.extend([
            f"",
            f"ORDER HISTORY:",
            format_order_history(context["order_history"]),
        ])

    # Kroger status
    kroger = context.get("kroger_status", {})
    if kroger.get("configured"):
        sections.extend([
            f"",
            f"KROGER STATUS: {kroger.get('auth_status', 'unknown')}",
        ])

    sections.extend([
        f"",
        f"=== USER MESSAGE ===",
    ])

    return "\n".join(sections)


# =============================================================================
# Context Snapshot
# =============================================================================


def build_context_snapshot(context: dict, input_tokens: int, output_tokens: int) -> dict:
    """Build context snapshot for logging to conversations table."""
    snapshot = {
        "shopping_list_size": len(context["current_shopping_list"]),
        "brand_prefs_count": len(context["brand_preferences"]),
        "recent_messages_count": len(context["recent_messages"]),
        "recent_notes_count": len(context.get("recent_recipe_notes", [])),
        "recipes_count": len(context.get("known_recipes", [])),
        "meal_plan_active": context.get("meal_plan") is not None,
        "pantry_items_count": len(context.get("pantry_items", [])),
        "preferences_count": len(context.get("preferences", [])),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }

    # Log which classifier sections were loaded
    if context.get("classifier_sections"):
        snapshot["classifier_sections"] = context["classifier_sections"]

    return snapshot


# =============================================================================
# Main API Call
# =============================================================================


def get_claude_response(
    user_message: str, user: str, db_session: Session
) -> tuple[str, dict, dict]:
    """Call Claude API with context and return (response_text, metadata, context).

    Args:
        user_message: The user's message text.
        user: Display name ("Erich" or "Lauren").
        db_session: Database session.

    Returns:
        Tuple of (response_text, metadata, context) where:
        - response_text: Raw response from Claude
        - metadata: Dict with input_tokens, output_tokens, model
        - context: The context dict that was sent to Claude

    Raises:
        Exception: If Claude API call fails.
    """
    context = build_context(user, db_session, user_message=user_message)
    system_prompt = load_system_prompt()

    formatted_context = format_context_for_claude(context)
    full_message = f"{formatted_context}\n\n{user_message}"

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
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
