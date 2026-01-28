"""Action parser for Claude responses with XML parsing and execution."""

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, date, timedelta
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
    Recipe,
    MealPlan,
    MealPlanStatus,
    PantryItem,
    Preference,
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


# =============================================================================
# Action Validation
# =============================================================================

# All known action types
KNOWN_ACTIONS = {
    # Phase 1
    "add_item", "remove_item", "clear_list", "finalize_order",
    "add_brand_preference", "add_recipe_note",
    # Phase 2 — recipes & meal planning
    "add_recipe", "add_meal", "remove_meal",
    "generate_list_from_meals", "complete_meal_plan",
    # Phase 3 — pantry & preferences
    "update_preference", "add_pantry_item", "update_pantry_item", "remove_pantry_item",
    # Phase 4 — Kroger
    "resolve_kroger_product", "confirm_kroger_product", "add_to_kroger_cart",
}


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

    elif action_type == "add_recipe":
        if not data.get("name"):
            raise ValidationError("Recipe name is required")
        if not data.get("ingredients"):
            raise ValidationError("Recipe ingredients are required")

    elif action_type == "add_meal":
        if not data.get("meal_name"):
            raise ValidationError("Meal name is required")

    elif action_type == "remove_meal":
        if not data.get("meal_name"):
            raise ValidationError("Meal name is required for removal")

    elif action_type == "update_preference":
        if not data.get("user") or not data.get("category") or not data.get("value"):
            raise ValidationError("User, category, and value required for preference update")

    elif action_type == "add_pantry_item":
        if not data.get("item_name"):
            raise ValidationError("Pantry item name is required")

    elif action_type == "update_pantry_item":
        if not data.get("item_name"):
            raise ValidationError("Pantry item name is required for update")

    elif action_type == "remove_pantry_item":
        if not data.get("item_name"):
            raise ValidationError("Pantry item name is required for removal")

    elif action_type == "resolve_kroger_product":
        if not data.get("item_name"):
            raise ValidationError("Item name is required for Kroger product search")

    elif action_type == "confirm_kroger_product":
        if not data.get("item_name") or not data.get("kroger_product_id"):
            raise ValidationError("Item name and kroger_product_id required")

    elif action_type in ("clear_list", "finalize_order", "generate_list_from_meals",
                         "complete_meal_plan", "add_to_kroger_cart"):
        pass  # No validation needed

    elif action_type not in KNOWN_ACTIONS:
        logger.warning(f"Unknown action type: {action_type}")


# =============================================================================
# Action Execution Functions — Phase 1 (Shopping List, Brand Prefs, Recipe Notes)
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

    # Include optional extended fields
    if data.get("kroger_product_id"):
        new_item["kroger_product_id"] = data["kroger_product_id"].strip()
    if data.get("from_recipe"):
        new_item["from_recipe"] = data["from_recipe"].strip()

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

    # Try to link to existing recipe
    normalized = normalize_recipe_name(recipe_name)
    recipe = (
        db_session.query(Recipe)
        .filter(Recipe.name.ilike(f"%{recipe_name}%"))
        .first()
    )

    new_note = RecipeNote(
        recipe_id=recipe.id if recipe else None,
        recipe_name=recipe_name,
        recipe_name_normalized=normalized,
        user=user,
        note_text=note_text,
        note_type=note_type,
        outcome=outcome,
    )
    db_session.add(new_note)
    logger.info(f"Added recipe note for: {recipe_name}")


# =============================================================================
# Action Execution Functions — Phase 2 (Recipes & Meal Planning)
# =============================================================================


def execute_add_recipe(data: dict, db_session: Session) -> int:
    """Add a new recipe to the database.

    Returns:
        The ID of the created recipe.
    """
    name = data["name"].strip()

    # Parse ingredients: comma-separated string -> list of dicts
    ingredients_str = data.get("ingredients", "")
    ingredients = [
        {"item": item.strip()}
        for item in ingredients_str.split(",")
        if item.strip()
    ]

    # Parse tags: comma-separated string -> list of strings
    tags_str = data.get("tags", "")
    tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []

    instructions = data.get("instructions", "").strip() or None
    cuisine = data.get("cuisine", "").strip() or None

    recipe = Recipe(
        name=name,
        ingredients=ingredients,
        instructions=instructions,
        cuisine=cuisine,
        tags=tags or None,
    )
    db_session.add(recipe)
    db_session.flush()  # Get the ID

    logger.info(f"Added recipe: {name} (id={recipe.id})")
    return recipe.id


def _get_or_create_active_meal_plan(db_session: Session) -> MealPlan:
    """Get the current PLANNING meal plan, or create one if none exists."""
    plan = (
        db_session.query(MealPlan)
        .filter(MealPlan.status == MealPlanStatus.PLANNING)
        .order_by(MealPlan.created_at.desc())
        .first()
    )
    if not plan:
        # Find an unused week_start_date (unique constraint exists on this column).
        # Start from today and increment if a completed/finalized plan already
        # occupies that date.
        start = date.today()
        while True:
            existing = (
                db_session.query(MealPlan)
                .filter(MealPlan.week_start_date == start)
                .first()
            )
            if not existing:
                break
            start = start + timedelta(days=1)

        plan = MealPlan(
            week_start_date=start,
            meals=[],
            status=MealPlanStatus.PLANNING,
        )
        db_session.add(plan)
        db_session.flush()
    return plan


def execute_add_meal(data: dict, db_session: Session) -> None:
    """Add a meal to the active meal plan."""
    plan = _get_or_create_active_meal_plan(db_session)

    meal_entry = {
        "meal_name": data["meal_name"].strip(),
        "added_at": datetime.now().isoformat(),
    }

    if data.get("recipe_id"):
        try:
            meal_entry["recipe_id"] = int(data["recipe_id"])
        except (ValueError, TypeError):
            pass

    if data.get("notes"):
        meal_entry["notes"] = data["notes"].strip()

    # Initialize meals if None
    if plan.meals is None:
        plan.meals = []

    # Trigger SQLAlchemy change detection
    plan.meals = plan.meals + [meal_entry]
    logger.info(f"Added meal to plan: {meal_entry['meal_name']}")


def execute_remove_meal(data: dict, db_session: Session) -> bool:
    """Remove a meal from the active meal plan.

    Returns:
        True if meal was found and removed, False otherwise.
    """
    plan = (
        db_session.query(MealPlan)
        .filter(MealPlan.status == MealPlanStatus.PLANNING)
        .order_by(MealPlan.created_at.desc())
        .first()
    )
    if not plan or not plan.meals:
        return False

    meal_name = data["meal_name"].strip().lower()
    remaining = [
        m for m in plan.meals
        if m.get("meal_name", "").lower() != meal_name
    ]

    if len(remaining) == len(plan.meals):
        logger.info(f"Meal not found for removal: {data['meal_name']}")
        return False

    plan.meals = remaining
    logger.info(f"Removed meal from plan: {data['meal_name']}")
    return True


def execute_generate_list_from_meals(db_session: Session) -> int:
    """Generate shopping list items from all meals in the active plan.

    Returns:
        Number of items added.
    """
    plan = (
        db_session.query(MealPlan)
        .filter(MealPlan.status == MealPlanStatus.PLANNING)
        .order_by(MealPlan.created_at.desc())
        .first()
    )
    if not plan or not plan.meals:
        logger.info("No active meal plan or no meals to generate list from")
        return 0

    active_list = get_or_create_active_list(db_session)

    # Build set of existing item names (lowercase) for dedup
    existing_names = set()
    if active_list.items:
        existing_names = {
            item.get("name", "").lower()
            for item in active_list.items
        }

    items_added = 0
    for meal in plan.meals:
        recipe_id = meal.get("recipe_id")
        if not recipe_id:
            continue

        recipe = db_session.query(Recipe).filter(Recipe.id == recipe_id).first()
        if not recipe or not recipe.ingredients:
            continue

        for ingredient in recipe.ingredients:
            item_name = ingredient.get("item", "").strip()
            if not item_name:
                continue

            # Skip if already on list (case-insensitive)
            if item_name.lower() in existing_names:
                continue

            new_item = {
                "name": item_name,
                "quantity": 1,
                "unit": "",
                "brand": None,
                "added_by": "meal plan",
                "added_at": datetime.now().isoformat(),
                "from_recipe": recipe.name,
            }

            # Check for brand preference
            from .claude_service import get_brand_preference
            pref = get_brand_preference(item_name, db_session)
            if pref:
                new_item["brand"] = pref["brand"]
                if pref.get("kroger_product_id"):
                    new_item["kroger_product_id"] = pref["kroger_product_id"]

            if active_list.items is None:
                active_list.items = []

            active_list.items = active_list.items + [new_item]
            existing_names.add(item_name.lower())
            items_added += 1

    logger.info(f"Generated {items_added} items from meal plan")
    return items_added


def execute_complete_meal_plan(db_session: Session) -> bool:
    """Mark the active meal plan as COMPLETED.

    Returns:
        True if a plan was completed, False if no active plan.
    """
    plan = (
        db_session.query(MealPlan)
        .filter(MealPlan.status == MealPlanStatus.PLANNING)
        .order_by(MealPlan.created_at.desc())
        .first()
    )
    if not plan:
        logger.info("No active meal plan to complete")
        return False

    plan.status = MealPlanStatus.COMPLETED
    plan.updated_at = datetime.now()
    logger.info(f"Completed meal plan {plan.id}")
    return True


# =============================================================================
# Action Execution Functions — Phase 3 (Pantry & Preferences)
# =============================================================================


def execute_update_preference(data: dict, db_session: Session) -> None:
    """Update a user preference (dietary, dislikes, loves, allergies)."""
    user = data["user"].strip().lower()
    # Capitalize first letter for storage
    user = user.capitalize()
    category = data["category"].strip().lower()
    value = data["value"].strip()

    # Find existing preference for this user
    pref = (
        db_session.query(Preference)
        .filter(Preference.user == user)
        .first()
    )

    if not pref:
        pref = Preference(user=user, data={})
        db_session.add(pref)
        db_session.flush()

    # Merge into data JSON
    pref_data = pref.data or {}

    # For list-type categories, append to list
    if category in ("dietary", "dislikes", "loves", "allergies"):
        if category not in pref_data:
            pref_data[category] = []
        if isinstance(pref_data[category], str):
            pref_data[category] = [pref_data[category]]
        if value not in pref_data[category]:
            pref_data[category].append(value)
    else:
        pref_data[category] = value

    pref.data = pref_data
    pref.updated_at = datetime.now()
    logger.info(f"Updated preference for {user}: {category} = {value}")


def execute_add_pantry_item(data: dict, db_session: Session) -> None:
    """Add or update a pantry item (upsert by item_name, case-insensitive)."""
    item_name = data["item_name"].strip()

    # Check for existing (case-insensitive)
    existing = (
        db_session.query(PantryItem)
        .filter(PantryItem.item_name.ilike(item_name))
        .first()
    )

    quantity = None
    if data.get("quantity"):
        try:
            quantity = float(data["quantity"])
        except (ValueError, TypeError):
            pass

    unit = data.get("unit", "").strip() or None

    if existing:
        if quantity is not None:
            existing.quantity = quantity
        if unit:
            existing.unit = unit
        existing.updated_at = datetime.now()
        logger.info(f"Updated pantry item: {item_name}")
    else:
        new_item = PantryItem(
            item_name=item_name,
            quantity=quantity,
            unit=unit,
        )
        db_session.add(new_item)
        logger.info(f"Added pantry item: {item_name}")


def execute_update_pantry_item(data: dict, db_session: Session) -> bool:
    """Update an existing pantry item.

    Returns:
        True if item was found and updated, False otherwise.
    """
    item_name = data["item_name"].strip()

    existing = (
        db_session.query(PantryItem)
        .filter(PantryItem.item_name.ilike(item_name))
        .first()
    )

    if not existing:
        logger.info(f"Pantry item not found for update: {item_name}")
        return False

    if data.get("quantity"):
        try:
            existing.quantity = float(data["quantity"])
        except (ValueError, TypeError):
            pass

    if data.get("unit"):
        existing.unit = data["unit"].strip()

    existing.updated_at = datetime.now()
    logger.info(f"Updated pantry item: {item_name}")
    return True


def execute_remove_pantry_item(data: dict, db_session: Session) -> bool:
    """Remove a pantry item.

    Returns:
        True if item was found and removed, False otherwise.
    """
    item_name = data["item_name"].strip()

    existing = (
        db_session.query(PantryItem)
        .filter(PantryItem.item_name.ilike(item_name))
        .first()
    )

    if not existing:
        logger.info(f"Pantry item not found for removal: {item_name}")
        return False

    db_session.delete(existing)
    logger.info(f"Removed pantry item: {item_name}")
    return True


# =============================================================================
# Action Execution Functions — Phase 4 (Kroger Integration)
# =============================================================================


def execute_resolve_kroger_product(data: dict, db_session: Session) -> dict:
    """Search Kroger for a product and return results.

    Returns:
        Dict with search results or error info.
    """
    try:
        from .kroger_service import search_products, is_configured

        if not is_configured():
            return {"error": "Kroger integration is not configured"}

        item_name = data["item_name"].strip()
        brand_hint = data.get("brand_hint", "").strip() or None

        results = search_products(item_name, brand=brand_hint, limit=5)
        logger.info(f"Kroger search for '{item_name}': {len(results)} results")
        return {"results": results, "item_name": item_name}

    except Exception as e:
        logger.error(f"Kroger product search error: {e}")
        return {"error": str(e)}


def execute_confirm_kroger_product(data: dict, db_session: Session) -> None:
    """Confirm a Kroger product selection, updating brand preference and shopping list item."""
    item_name = data["item_name"].strip()
    kroger_product_id = data["kroger_product_id"].strip()
    brand = data.get("brand", "").strip()
    size = data.get("size", "").strip()

    # Update or create brand preference with kroger_product_id
    generic_item = item_name.lower()
    existing_pref = (
        db_session.query(BrandPreference)
        .filter(BrandPreference.generic_item == generic_item)
        .first()
    )

    if existing_pref:
        existing_pref.kroger_product_id = kroger_product_id
        if brand:
            existing_pref.preferred_brand = brand
        existing_pref.updated_at = datetime.now()
    elif brand:
        new_pref = BrandPreference(
            generic_item=generic_item,
            preferred_brand=brand,
            kroger_product_id=kroger_product_id,
            confidence=BrandConfidence.CONFIRMED,
        )
        db_session.add(new_pref)

    # Update the shopping list item with kroger_product_id
    active_list = get_or_create_active_list(db_session)
    if active_list.items:
        updated_items = []
        for item in active_list.items:
            if item.get("name", "").lower() == generic_item:
                item = dict(item)  # Copy to avoid mutation issues
                item["kroger_product_id"] = kroger_product_id
                if brand:
                    item["brand"] = brand
            updated_items.append(item)
        active_list.items = updated_items

    logger.info(f"Confirmed Kroger product for {item_name}: {kroger_product_id}")


def execute_add_to_kroger_cart(db_session: Session) -> dict:
    """Add all resolved shopping list items to the Kroger cart.

    Returns:
        Dict with result info (success, unresolved items, or error).
    """
    try:
        from .kroger_service import add_items_to_cart, is_user_authenticated, is_configured, get_auth_url

        if not is_configured():
            return {"error": "Kroger integration is not configured"}

        if not is_user_authenticated():
            auth_url = get_auth_url()
            return {"error": "not_authenticated", "auth_url": auth_url}

        active_list = get_or_create_active_list(db_session)
        if not active_list.items:
            return {"error": "Shopping list is empty"}

        # Split into resolved and unresolved
        resolved = []
        unresolved = []
        for item in active_list.items:
            if item.get("kroger_product_id"):
                resolved.append({
                    "upc": item["kroger_product_id"],
                    "quantity": int(item.get("quantity", 1)),
                })
            else:
                unresolved.append(item.get("name", "Unknown"))

        if unresolved:
            return {
                "error": "unresolved_items",
                "unresolved": unresolved,
                "resolved_count": len(resolved),
            }

        # All resolved — add to cart
        success = add_items_to_cart(resolved)
        if success:
            logger.info(f"Added {len(resolved)} items to Kroger cart")
            return {"success": True, "items_added": len(resolved)}
        else:
            return {"error": "Failed to add items to Kroger cart"}

    except Exception as e:
        logger.error(f"Kroger cart error: {e}")
        return {"error": str(e)}


# =============================================================================
# Action Dispatcher
# =============================================================================


def execute_action(action: Action, db_session: Session) -> Any:
    """Execute a single action.

    Args:
        action: The action to execute.
        db_session: Database session.

    Returns:
        Result of the action (varies by type).

    Raises:
        Exception: If execution fails.
    """
    action_type = action.action_type
    data = action.data

    # Phase 1
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

    # Phase 2 — Recipes & Meal Planning
    elif action_type == "add_recipe":
        return execute_add_recipe(data, db_session)

    elif action_type == "add_meal":
        execute_add_meal(data, db_session)

    elif action_type == "remove_meal":
        execute_remove_meal(data, db_session)

    elif action_type == "generate_list_from_meals":
        return execute_generate_list_from_meals(db_session)

    elif action_type == "complete_meal_plan":
        execute_complete_meal_plan(db_session)

    # Phase 3 — Pantry & Preferences
    elif action_type == "update_preference":
        execute_update_preference(data, db_session)

    elif action_type == "add_pantry_item":
        execute_add_pantry_item(data, db_session)

    elif action_type == "update_pantry_item":
        execute_update_pantry_item(data, db_session)

    elif action_type == "remove_pantry_item":
        execute_remove_pantry_item(data, db_session)

    # Phase 4 — Kroger
    elif action_type == "resolve_kroger_product":
        return execute_resolve_kroger_product(data, db_session)

    elif action_type == "confirm_kroger_product":
        execute_confirm_kroger_product(data, db_session)

    elif action_type == "add_to_kroger_cart":
        return execute_add_to_kroger_cart(db_session)

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
