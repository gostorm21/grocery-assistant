"""Action parser for Claude responses with XML parsing and execution."""

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .models import (
    ShoppingList,
    ShoppingListStatus,
    BrandPreference,
    BrandConfidence,
    RecipeNote,
    NoteType,
    NoteOutcome,
    normalize_recipe_name,
)

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when action validation fails."""

    pass


class ParseError(Exception):
    """Raised when XML parsing fails."""

    pass


@dataclass
class Action:
    """Represents a parsed action from Claude's response."""

    action_type: str
    data: dict[str, Any]


def extract_between_tags(text: str, tag: str) -> str | None:
    """Extract content between XML tags.

    Args:
        text: The full text to search.
        tag: The tag name (without angle brackets).

    Returns:
        The content between the tags, or None if not found.
    """
    pattern = rf"<{tag}>(.*?)</{tag}>"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def extract_text_fallback(text: str) -> str | None:
    """Attempt to extract readable text from a malformed response.

    Used as a fallback when normal parsing fails.
    """
    # Try to find response tag content
    response = extract_between_tags(text, "response")
    if response:
        return response

    # Try to find any text that looks like a response
    # Strip XML tags and return plain text
    plain_text = re.sub(r"<[^>]+>", "", text).strip()
    if plain_text:
        return plain_text

    return None


def parse_action_element(element: ET.Element) -> Action:
    """Parse a single action XML element into an Action object.

    Args:
        element: An XML element representing an action.

    Returns:
        An Action object with type and data.
    """
    action_type = element.tag
    data = {}

    # Extract all child elements as data fields
    for child in element:
        # Get text content, strip whitespace
        text = child.text.strip() if child.text else ""
        data[child.tag] = text

    return Action(action_type=action_type, data=data)


def parse_actions_xml(actions_xml: str) -> list[Action]:
    """Parse the actions XML block into a list of Action objects.

    Args:
        actions_xml: The XML content inside <actions> tags.

    Returns:
        List of Action objects.

    Raises:
        ParseError: If XML parsing fails.
    """
    # Handle noop
    if "<noop/>" in actions_xml or "<noop />" in actions_xml:
        return []

    # Wrap in root element for parsing
    wrapped_xml = f"<root>{actions_xml}</root>"

    try:
        root = ET.fromstring(wrapped_xml)
    except ET.ParseError as e:
        raise ParseError(f"Failed to parse actions XML: {e}")

    actions = []
    for child in root:
        # Skip noop elements
        if child.tag == "noop":
            continue
        actions.append(parse_action_element(child))

    return actions


def validate_action(action: Action) -> None:
    """Validate action data before execution.

    Args:
        action: The action to validate.

    Raises:
        ValidationError: If validation fails.
    """
    action_type = action.action_type
    data = action.data

    if action_type == "add_item":
        if not data.get("name"):
            raise ValidationError("Item name is required")
        if not data.get("name").strip():
            raise ValidationError("Item name cannot be empty")
        if data.get("quantity"):
            try:
                float(data["quantity"])
            except (ValueError, TypeError):
                raise ValidationError("Quantity must be numeric")

    elif action_type == "remove_item":
        if not data.get("name"):
            raise ValidationError("Item name required for removal")

    elif action_type == "add_brand_preference":
        if not data.get("item") or not data.get("brand"):
            raise ValidationError("Both item and brand required")

    elif action_type == "add_recipe_note":
        if not data.get("recipe_name") or not data.get("note_text"):
            raise ValidationError("Recipe name and note text required")

    elif action_type == "clear_list":
        pass  # No validation needed

    elif action_type == "finalize_order":
        pass  # Validation happens during execution (check for empty list)

    else:
        logger.warning(f"Unknown action type: {action_type}")


# =============================================================================
# Action Execution Functions
# =============================================================================


def get_or_create_active_list(db_session: Session) -> ShoppingList:
    """Get the current active list, or create one if none exists."""
    active_list = (
        db_session.query(ShoppingList)
        .filter(ShoppingList.status == ShoppingListStatus.ACTIVE)
        .first()
    )
    if not active_list:
        active_list = ShoppingList(status=ShoppingListStatus.ACTIVE, items=[])
        db_session.add(active_list)
        db_session.flush()
    return active_list


def execute_add_item(data: dict, db_session: Session) -> None:
    """Add an item to the active shopping list."""
    active_list = get_or_create_active_list(db_session)

    # Parse quantity
    quantity = 1
    if data.get("quantity"):
        try:
            quantity = float(data["quantity"])
        except (ValueError, TypeError):
            quantity = 1

    new_item = {
        "name": data["name"].strip(),
        "quantity": quantity,
        "unit": data.get("unit", "").strip(),
        "brand": data.get("brand", "").strip() or None,
        "added_by": data.get("added_by", "").strip(),
        "added_at": datetime.now().isoformat(),
    }

    # Initialize items if None
    if active_list.items is None:
        active_list.items = []

    # Create new list to trigger SQLAlchemy change detection
    active_list.items = active_list.items + [new_item]
    logger.info(f"Added item: {new_item['name']}")


def execute_remove_item(data: dict, db_session: Session) -> bool:
    """Remove an item from the active shopping list.

    Returns:
        True if item was found and removed, False otherwise.
    """
    active_list = get_or_create_active_list(db_session)

    if not active_list.items:
        return False

    item_name = data["name"].strip().lower()

    # Find matching items (case-insensitive)
    remaining_items = []
    removed = False
    for item in active_list.items:
        if item_name in item.get("name", "").lower() and not removed:
            # Remove first match only
            removed = True
            logger.info(f"Removed item: {item.get('name')}")
        else:
            remaining_items.append(item)

    active_list.items = remaining_items
    return removed


def execute_clear_list(db_session: Session) -> None:
    """Clear all items from the active shopping list."""
    active_list = get_or_create_active_list(db_session)
    active_list.items = []
    logger.info("Cleared shopping list")


def execute_finalize_order(db_session: Session) -> bool:
    """Finalize the current order and start a new list.

    Returns:
        True if successful, False if list was empty.
    """
    active_list = get_or_create_active_list(db_session)

    if not active_list.items:
        logger.warning("Cannot finalize empty list")
        return False

    # Archive current list
    active_list.status = ShoppingListStatus.ORDERED
    active_list.ordered_at = datetime.now()

    # Create new active list
    new_list = ShoppingList(status=ShoppingListStatus.ACTIVE, items=[])
    db_session.add(new_list)

    logger.info(f"Finalized order with {len(active_list.items)} items")
    return True


def execute_add_brand_preference(data: dict, db_session: Session) -> None:
    """Add or update a brand preference."""
    generic_item = data["item"].strip().lower()
    preferred_brand = data["brand"].strip()

    # Parse confidence
    confidence_str = data.get("confidence", "confirmed").lower()
    confidence = (
        BrandConfidence.INFERRED
        if confidence_str == "inferred"
        else BrandConfidence.CONFIRMED
    )

    # Check if preference already exists
    existing = (
        db_session.query(BrandPreference)
        .filter(BrandPreference.generic_item == generic_item)
        .first()
    )

    if existing:
        existing.preferred_brand = preferred_brand
        existing.confidence = confidence
        existing.updated_at = datetime.now()
        logger.info(f"Updated brand preference: {generic_item} -> {preferred_brand}")
    else:
        new_pref = BrandPreference(
            generic_item=generic_item,
            preferred_brand=preferred_brand,
            confidence=confidence,
        )
        db_session.add(new_pref)
        logger.info(f"Added brand preference: {generic_item} -> {preferred_brand}")


def execute_add_recipe_note(data: dict, db_session: Session) -> None:
    """Add a recipe note."""
    recipe_name = data["recipe_name"].strip()
    user = data.get("user", "").strip()
    note_text = data["note_text"].strip()

    # Parse note_type
    note_type_str = data.get("note_type", "general").lower()
    note_type_map = {
        "ingredient_change": NoteType.INGREDIENT_CHANGE,
        "technique": NoteType.TECHNIQUE,
        "timing": NoteType.TIMING,
        "general": NoteType.GENERAL,
    }
    note_type = note_type_map.get(note_type_str, NoteType.GENERAL)

    # Parse outcome
    outcome_str = data.get("outcome", "neutral").lower()
    outcome_map = {
        "better": NoteOutcome.BETTER,
        "worse": NoteOutcome.WORSE,
        "neutral": NoteOutcome.NEUTRAL,
    }
    outcome = outcome_map.get(outcome_str, NoteOutcome.NEUTRAL)

    new_note = RecipeNote(
        recipe_name=recipe_name,
        recipe_name_normalized=normalize_recipe_name(recipe_name),
        user=user,
        note_text=note_text,
        note_type=note_type,
        outcome=outcome,
    )
    db_session.add(new_note)
    logger.info(f"Added recipe note for: {recipe_name}")


def execute_action(action: Action, db_session: Session) -> None:
    """Execute a single action.

    Args:
        action: The action to execute.
        db_session: Database session.

    Raises:
        Exception: If execution fails.
    """
    action_type = action.action_type
    data = action.data

    if action_type == "add_item":
        execute_add_item(data, db_session)

    elif action_type == "remove_item":
        execute_remove_item(data, db_session)

    elif action_type == "clear_list":
        execute_clear_list(db_session)

    elif action_type == "finalize_order":
        execute_finalize_order(db_session)

    elif action_type == "add_brand_preference":
        execute_add_brand_preference(data, db_session)

    elif action_type == "add_recipe_note":
        execute_add_recipe_note(data, db_session)

    else:
        logger.warning(f"Unknown action type, skipping: {action_type}")


# =============================================================================
# Main Processing Function
# =============================================================================


def process_claude_response(response_text: str, db_session: Session) -> str:
    """Parse Claude response and execute actions, return natural language response.

    This function:
    1. Extracts the <response> content (what the user sees)
    2. Extracts and parses the <actions> block
    3. Validates and executes each action
    4. Returns the natural language response

    Even if action parsing/execution fails, the response is still returned.

    Args:
        response_text: Raw response from Claude.
        db_session: Database session.

    Returns:
        The natural language response to send to the user.
    """
    natural_response = None

    try:
        # Extract response content
        natural_response = extract_between_tags(response_text, "response")

        if not natural_response:
            logger.warning("No <response> tag found in Claude output")
            natural_response = extract_text_fallback(response_text)

        # Extract actions
        actions_xml = extract_between_tags(response_text, "actions")

        # If no actions or noop, just return response
        if not actions_xml or "<noop/>" in actions_xml or "<noop />" in actions_xml:
            return natural_response or "I understand."

        # Parse actions
        try:
            actions = parse_actions_xml(actions_xml)
        except ParseError as e:
            logger.error(f"Failed to parse actions: {e}")
            return natural_response or "I understand, but had trouble processing the action."

        # Execute each action
        for action in actions:
            try:
                validate_action(action)
                execute_action(action, db_session)
            except ValidationError as e:
                logger.error(f"Action validation failed for {action.action_type}: {e}")
                # Continue with other actions
            except Exception as e:
                logger.exception(f"Action execution failed for {action.action_type}: {e}")
                # Continue with other actions

        # Commit all changes
        db_session.commit()

        return natural_response or "Done."

    except Exception as e:
        logger.exception(f"Response parsing error: {e}")
        # Try to return something useful
        if natural_response:
            return natural_response
        fallback = extract_text_fallback(response_text)
        return fallback or "Sorry, I had trouble processing that."
