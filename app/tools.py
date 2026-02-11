"""Tool definitions and handlers for the agentic tool-use loop.

Replaces action_parser.py. Each tool is a Claude tool_use function with a
handler that executes against the normalized ingredient data model.
"""

import json
from datetime import datetime, date, timedelta

from sqlalchemy.orm import Session

from .models import (
    ShoppingList,
    ShoppingListStatus,
    Conversation,
    RecipeNote,
    NoteType,
    NoteOutcome,
    Recipe,
    MealPlan,
    MealPlanStatus,
    PantryItem,
    Preference,
    Ingredient,
    RecipeIngredient,
    ShoppingListItem,
    EventLog,
    ActionType,
    normalize_recipe_name,
    normalize_ingredient_name,
)


# =============================================================================
# Tool Definitions (sent to Claude in the tools parameter)
# =============================================================================

TOOL_DEFINITIONS = [
    # --- Read tools ---
    {
        "name": "get_shopping_list",
        "description": "Get the current active shopping list with all items, including ingredient names, brands, Kroger IDs, and checked-off status.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_ingredients",
        "description": "Search known ingredients. Returns ingredient records with brand preferences, Kroger product IDs, and categories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Filter by ingredient name (partial match).",
                },
                "has_kroger_id": {
                    "type": "boolean",
                    "description": "If true, only return ingredients with a Kroger product ID. If false, only those without.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_recipes",
        "description": "Search saved recipes. Returns recipes with their linked ingredients (names, quantities, units).",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Filter by recipe name (partial match).",
                },
                "cuisine": {
                    "type": "string",
                    "description": "Filter by cuisine type.",
                },
                "tags": {
                    "type": "string",
                    "description": "Filter by tag (partial match against tags JSON array).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 20).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_meal_plan",
        "description": "Get the current active meal plan with all planned meals.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_pantry",
        "description": "Get all pantry items with quantities and units.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_preferences",
        "description": "Get dietary preferences for one or all users.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user": {
                    "type": "string",
                    "description": "Filter by user name (e.g. 'Erich', 'Lauren'). Omit for all.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_recipe_notes",
        "description": "Get cooking feedback notes, optionally filtered by recipe name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipe_name": {
                    "type": "string",
                    "description": "Filter notes by recipe name (partial match).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_order_history",
        "description": "Get past ordered shopping lists with item counts and dates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max orders to return (default 5).",
                },
            },
            "required": [],
        },
    },
    # --- Write tools ---
    {
        "name": "add_item",
        "description": "Add an item to the active shopping list. Auto-links to existing Ingredient records or creates new ones.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Item name (e.g. 'Chicken Breast', 'Whole Milk').",
                },
                "added_by": {
                    "type": "string",
                    "description": "Who is adding this item ('Erich' or 'Lauren'). MUST match the current user.",
                },
                "quantity": {
                    "type": "number",
                    "description": "Quantity (default 1).",
                },
                "unit": {
                    "type": "string",
                    "description": "Unit of measure (e.g. 'gallon', 'lb', 'dozen').",
                },
            },
            "required": ["name", "added_by"],
        },
    },
    {
        "name": "remove_item",
        "description": "Remove an item from the active shopping list by ingredient name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the item to remove.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "update_item",
        "description": "Update quantity or unit of an existing shopping list item.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_name": {
                    "type": "string",
                    "description": "Name of item to update.",
                },
                "quantity": {
                    "type": "number",
                    "description": "New quantity.",
                },
                "unit": {
                    "type": "string",
                    "description": "New unit (optional).",
                },
            },
            "required": ["item_name"],
        },
    },
    {
        "name": "clear_list",
        "description": "Remove all items from the active shopping list.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "finalize_order",
        "description": "Archive the current shopping list as ordered and create a new empty active list.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "update_ingredient",
        "description": "Update an ingredient's preferred brand, size, or category. Use this instead of the old add_brand_preference.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Ingredient name to update.",
                },
                "preferred_brand": {
                    "type": "string",
                    "description": "Preferred brand name.",
                },
                "preferred_size": {
                    "type": "string",
                    "description": "Preferred size (e.g. '1 lb pack', '1 gallon').",
                },
                "category": {
                    "type": "string",
                    "description": "Category (e.g. 'produce', 'dairy', 'meat').",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "add_recipe_note",
        "description": "Store cooking feedback or tips for a recipe.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipe_name": {
                    "type": "string",
                    "description": "Name of the recipe.",
                },
                "user": {
                    "type": "string",
                    "description": "Who is leaving the note ('Erich' or 'Lauren').",
                },
                "note_text": {
                    "type": "string",
                    "description": "The feedback text.",
                },
                "title": {
                    "type": "string",
                    "description": "Optional short title for scannable display.",
                },
                "note_type": {
                    "type": "string",
                    "enum": ["ingredient_change", "technique", "timing", "general"],
                    "description": "Type of note (default: general).",
                },
                "outcome": {
                    "type": "string",
                    "enum": ["better", "worse", "neutral"],
                    "description": "Outcome of the change (default: neutral).",
                },
            },
            "required": ["recipe_name", "user", "note_text"],
        },
    },
    {
        "name": "add_recipe",
        "description": "Save a new recipe with structured ingredients and instructions. Each ingredient is auto-linked to the Ingredient table.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Recipe name.",
                },
                "ingredients": {
                    "type": "array",
                    "description": "List of ingredients with structured data.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Ingredient name."},
                            "quantity": {"type": "number", "description": "Amount needed."},
                            "unit": {"type": "string", "description": "Unit of measure."},
                            "prep_notes": {"type": "string", "description": "Preparation notes (e.g. 'diced', 'minced')."},
                        },
                        "required": ["name"],
                    },
                },
                "instructions": {
                    "type": "string",
                    "description": "Step-by-step cooking instructions.",
                },
                "cuisine": {
                    "type": "string",
                    "description": "Cuisine type (e.g. 'Mexican', 'Italian').",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for categorization (e.g. ['weeknight', 'comfort']).",
                },
            },
            "required": ["name", "ingredients"],
        },
    },
    {
        "name": "add_meal",
        "description": "Add a meal to the active meal plan.",
        "input_schema": {
            "type": "object",
            "properties": {
                "meal_name": {
                    "type": "string",
                    "description": "Name of the meal.",
                },
                "recipe_id": {
                    "type": "integer",
                    "description": "ID of a saved recipe to link (optional).",
                },
                "notes": {
                    "type": "string",
                    "description": "Special instructions for this meal.",
                },
            },
            "required": ["meal_name"],
        },
    },
    {
        "name": "remove_meal",
        "description": "Remove a meal from the active meal plan.",
        "input_schema": {
            "type": "object",
            "properties": {
                "meal_name": {
                    "type": "string",
                    "description": "Name of the meal to remove.",
                },
            },
            "required": ["meal_name"],
        },
    },
    {
        "name": "generate_list_from_meals",
        "description": "Generate shopping list items from all meals in the active plan. Queries RecipeIngredients, checks pantry, deduplicates against existing list items.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "complete_meal_plan",
        "description": "Mark the active meal plan as completed so a new one can be started.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "update_preference",
        "description": "Store or update a dietary preference for a user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user": {
                    "type": "string",
                    "description": "User name ('Erich', 'Lauren', or 'household').",
                },
                "category": {
                    "type": "string",
                    "description": "Preference category ('dietary', 'dislikes', 'loves', 'allergies').",
                },
                "value": {
                    "type": "string",
                    "description": "The preference value.",
                },
            },
            "required": ["user", "category", "value"],
        },
    },
    {
        "name": "add_pantry_item",
        "description": "Add or update a pantry item (upsert by name). Auto-links to Ingredient table.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_name": {
                    "type": "string",
                    "description": "Name of the pantry item.",
                },
                "quantity": {
                    "type": "number",
                    "description": "Quantity on hand.",
                },
                "unit": {
                    "type": "string",
                    "description": "Unit of measure.",
                },
            },
            "required": ["item_name"],
        },
    },
    {
        "name": "add_pantry_batch",
        "description": "Add multiple items to pantry at once. More efficient than calling add_pantry_item repeatedly.",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_name": {"type": "string", "description": "Name of pantry item."},
                            "quantity": {"type": "number", "description": "Optional quantity."},
                            "unit": {"type": "string", "description": "Optional unit."},
                        },
                        "required": ["item_name"],
                    },
                    "description": "Array of pantry items to add.",
                },
            },
            "required": ["items"],
        },
    },
    {
        "name": "update_pantry_item",
        "description": "Update an existing pantry item's quantity or unit.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_name": {
                    "type": "string",
                    "description": "Name of the pantry item to update.",
                },
                "quantity": {
                    "type": "number",
                    "description": "New quantity.",
                },
                "unit": {
                    "type": "string",
                    "description": "New unit.",
                },
            },
            "required": ["item_name"],
        },
    },
    {
        "name": "remove_pantry_item",
        "description": "Remove a pantry item (e.g. 'we're out of X').",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_name": {
                    "type": "string",
                    "description": "Name of the pantry item to remove.",
                },
            },
            "required": ["item_name"],
        },
    },
    {
        "name": "resolve_kroger_product",
        "description": "Search the Kroger catalog for a product. Returns top matches with brand, size, and price.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ingredient_name": {
                    "type": "string",
                    "description": "Ingredient name to search for.",
                },
                "brand_hint": {
                    "type": "string",
                    "description": "Optional brand to filter results.",
                },
            },
            "required": ["ingredient_name"],
        },
    },
    {
        "name": "confirm_kroger_product",
        "description": "Confirm a Kroger product match for an ingredient. Stores the kroger_product_id, brand, size, and price on the Ingredient record permanently.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ingredient_name": {
                    "type": "string",
                    "description": "Ingredient name to update.",
                },
                "kroger_product_id": {
                    "type": "string",
                    "description": "The Kroger product ID to store.",
                },
                "brand": {
                    "type": "string",
                    "description": "Brand name for this product.",
                },
                "size": {
                    "type": "string",
                    "description": "Product size description.",
                },
                "price": {
                    "type": "number",
                    "description": "Product price. IMPORTANT: Always pass this from the search results.",
                },
            },
            "required": ["ingredient_name", "kroger_product_id"],
        },
    },
    {
        "name": "add_to_kroger_cart",
        "description": "Add all shopping list items to the Kroger cart. All items must have resolved Kroger product IDs.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "check_off_item",
        "description": "Toggle the checked-off status of a shopping list item (for in-store use).",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the item to check off.",
                },
            },
            "required": ["name"],
        },
    },
    # --- Batch Operations ---
    {
        "name": "import_recipes_batch",
        "description": "Import multiple recipes at once in a single transaction. More efficient than calling add_recipe multiple times.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipes": {
                    "type": "array",
                    "description": "List of recipes to import.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Recipe name."},
                            "ingredients": {
                                "type": "array",
                                "description": "List of ingredients.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string", "description": "Ingredient name."},
                                        "quantity": {"type": "number", "description": "Amount needed."},
                                        "unit": {"type": "string", "description": "Unit of measure."},
                                    },
                                    "required": ["name"],
                                },
                            },
                            "instructions": {"type": "string", "description": "Cooking instructions."},
                            "cuisine": {"type": "string", "description": "Cuisine type."},
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Tags for categorization.",
                            },
                        },
                        "required": ["name", "ingredients"],
                    },
                },
            },
            "required": ["recipes"],
        },
    },
    {
        "name": "match_purchases_to_ingredients",
        "description": "Fetch Kroger purchase history and fuzzy match against ingredients missing Kroger IDs. Returns matches for user confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "update_recipe",
        "description": "Update an existing recipe - add/remove ingredients or update description.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipe_name": {
                    "type": "string",
                    "description": "Name of the recipe to update.",
                },
                "add_ingredients": {
                    "type": "array",
                    "description": "Ingredients to add to the recipe.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Ingredient name."},
                            "quantity": {"type": "number", "description": "Amount needed."},
                            "unit": {"type": "string", "description": "Unit of measure."},
                            "prep_notes": {"type": "string", "description": "Preparation notes."},
                        },
                        "required": ["name"],
                    },
                },
                "remove_ingredients": {
                    "type": "array",
                    "description": "Names of ingredients to remove.",
                    "items": {"type": "string"},
                },
                "update_description": {
                    "type": "string",
                    "description": "New description for the recipe.",
                },
            },
            "required": ["recipe_name"],
        },
    },
    {
        "name": "set_ingredient_alias",
        "description": "Add a shorthand alias for an ingredient. Use this when you learn a user's shorthand (e.g., 'dishwasher pods' = 'Simple Truth Dishwasher Detergent Pods'). Future lookups will match the alias.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ingredient_name": {
                    "type": "string",
                    "description": "The full/canonical ingredient name.",
                },
                "alias": {
                    "type": "string",
                    "description": "The shorthand alias to add.",
                },
            },
            "required": ["ingredient_name", "alias"],
        },
    },
    {
        "name": "set_purchase_source",
        "description": "Mark an ingredient as purchased from a specific store (not Kroger). Use for items from Sprouts, liquor store, Costco, farmer's market, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ingredient_name": {
                    "type": "string",
                    "description": "The ingredient name.",
                },
                "source": {
                    "type": "string",
                    "description": "Where to purchase: 'sprouts', 'liquor_store', 'costco', 'farmers_market', 'other', or null to reset to Kroger.",
                },
            },
            "required": ["ingredient_name", "source"],
        },
    },
    {
        "name": "get_non_kroger_items",
        "description": "Get shopping list items that need to be purchased elsewhere (not from Kroger). Groups by purchase source.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


def get_tool_definitions() -> list:
    """Return tool definitions for Claude API."""
    return TOOL_DEFINITIONS


# =============================================================================
# Helpers
# =============================================================================


def _get_or_create_ingredient(name: str, db_session: Session) -> Ingredient:
    """Find existing ingredient by normalized name or alias, or create new one."""
    normalized = normalize_ingredient_name(name)

    # First check exact normalized_name match
    ingredient = (
        db_session.query(Ingredient)
        .filter(Ingredient.normalized_name == normalized)
        .first()
    )

    # If not found, check aliases
    if not ingredient:
        # Query for ingredients where aliases JSON array contains this normalized name
        all_ingredients = db_session.query(Ingredient).filter(Ingredient.aliases.isnot(None)).all()
        for ing in all_ingredients:
            if ing.aliases and normalized in [normalize_ingredient_name(a) for a in ing.aliases]:
                ingredient = ing
                print(f"[_get_or_create_ingredient] Matched alias '{name}' to '{ing.name}'", flush=True)
                break

    # If still not found, create new
    if not ingredient:
        ingredient = Ingredient(
            name=name,
            normalized_name=normalized,
        )
        db_session.add(ingredient)
        db_session.flush()

    return ingredient


def _get_or_create_active_list(db_session: Session) -> ShoppingList:
    """Get the current active list, or create one if none exists."""
    active_list = (
        db_session.query(ShoppingList)
        .filter(ShoppingList.status == ShoppingListStatus.ACTIVE)
        .first()
    )
    if not active_list:
        active_list = ShoppingList(status=ShoppingListStatus.ACTIVE)
        db_session.add(active_list)
        db_session.flush()
    return active_list


def _get_or_create_active_meal_plan(db_session: Session) -> MealPlan:
    """Get the current PLANNING meal plan, or create one if none exists."""
    plan = (
        db_session.query(MealPlan)
        .filter(MealPlan.status == MealPlanStatus.PLANNING)
        .order_by(MealPlan.created_at.desc())
        .first()
    )
    if not plan:
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


def _log_event(
    db_session: Session,
    action_type: ActionType,
    input_summary: str,
    output_summary: str,
    related_ids: dict = None,
) -> None:
    """Record an EventLog entry for a write operation."""
    try:
        event = EventLog(
            action_type=action_type,
            input_summary=input_summary,
            output_summary=output_summary,
            related_ids=related_ids,
        )
        db_session.add(event)
    except Exception as e:
        print(f"[_log_event] Failed to log event: {e}", flush=True)


def _backfill_orphaned_notes(recipe: Recipe, db_session: Session) -> int:
    """Link orphaned recipe notes to a newly created recipe.

    Finds notes with matching recipe_name_normalized that have no recipe_id
    and links them to this recipe.

    Returns the count of notes linked.
    """
    from .models import normalize_recipe_name

    normalized = normalize_recipe_name(recipe.name)

    orphaned_notes = (
        db_session.query(RecipeNote)
        .filter(
            RecipeNote.recipe_id.is_(None),
            RecipeNote.recipe_name_normalized == normalized,
        )
        .all()
    )

    for note in orphaned_notes:
        note.recipe_id = recipe.id

    if orphaned_notes:
        print(f"[_backfill_orphaned_notes] Linked {len(orphaned_notes)} orphaned notes to recipe '{recipe.name}'", flush=True)

    return len(orphaned_notes)


# =============================================================================
# Read Tool Handlers
# =============================================================================


def execute_get_shopping_list(params: dict, db_session: Session, **kwargs) -> dict:
    """Get active shopping list items joined with Ingredient data."""
    print("[get_shopping_list] Called", flush=True)
    active_list = (
        db_session.query(ShoppingList)
        .filter(ShoppingList.status == ShoppingListStatus.ACTIVE)
        .first()
    )
    if not active_list:
        print("[get_shopping_list] No active list found", flush=True)
        return {"items": [], "list_id": None}

    items = (
        db_session.query(ShoppingListItem)
        .filter(ShoppingListItem.shopping_list_id == active_list.id)
        .all()
    )

    result_items = []
    for item in items:
        ing = item.ingredient
        result_items.append({
            "item_id": item.id,
            "name": ing.name,
            "quantity": item.quantity,
            "unit": item.unit,
            "added_by": item.added_by,
            "checked_off": item.checked_off,
            "preferred_brand": ing.preferred_brand,
            "kroger_product_id": ing.kroger_product_id,
            "from_recipe_id": item.from_recipe_id,
            "purchase_source": ing.purchase_source,
        })

    print(f"[get_shopping_list] SUCCESS: {len(result_items)} items", flush=True)
    return {"items": result_items, "list_id": active_list.id, "item_count": len(result_items)}


def execute_get_ingredients(params: dict, db_session: Session, **kwargs) -> dict:
    """Search known ingredients."""
    print(f"[get_ingredients] Called: {params}", flush=True)
    query = db_session.query(Ingredient)

    name_filter = params.get("name")
    if name_filter:
        normalized = normalize_ingredient_name(name_filter)
        query = query.filter(Ingredient.normalized_name.contains(normalized))

    has_kroger = params.get("has_kroger_id")
    if has_kroger is True:
        query = query.filter(Ingredient.kroger_product_id.isnot(None))
    elif has_kroger is False:
        query = query.filter(Ingredient.kroger_product_id.is_(None))

    ingredients = query.order_by(Ingredient.name).limit(50).all()
    result = [
        {
            "id": i.id,
            "name": i.name,
            "preferred_brand": i.preferred_brand,
            "preferred_size": i.preferred_size,
            "kroger_product_id": i.kroger_product_id,
            "category": i.category,
        }
        for i in ingredients
    ]
    print(f"[get_ingredients] SUCCESS: {len(result)} ingredients", flush=True)
    return {"ingredients": result, "count": len(result)}


def execute_get_recipes(params: dict, db_session: Session, **kwargs) -> dict:
    """Search saved recipes with linked ingredients."""
    print(f"[get_recipes] Called: {params}", flush=True)
    query = db_session.query(Recipe)

    if params.get("name"):
        query = query.filter(Recipe.name.ilike(f"%{params['name']}%"))
    if params.get("cuisine"):
        query = query.filter(Recipe.cuisine.ilike(f"%{params['cuisine']}%"))

    limit = params.get("limit", 20)
    recipes = query.order_by(Recipe.updated_at.desc()).limit(limit).all()

    result = []
    for r in recipes:
        # Get linked ingredients via junction table
        recipe_ings = (
            db_session.query(RecipeIngredient)
            .filter(RecipeIngredient.recipe_id == r.id)
            .all()
        )
        ingredients = [
            {
                "name": ri.ingredient.name,
                "quantity": ri.quantity,
                "unit": ri.unit,
                "prep_notes": ri.prep_notes,
            }
            for ri in recipe_ings
        ]

        recipe_data = {
            "id": r.id,
            "name": r.name,
            "ingredients": ingredients,
            "instructions": r.instructions,
            "cuisine": r.cuisine,
            "tags": r.tags,
        }

        # Query recipe notes for this recipe
        notes = (
            db_session.query(RecipeNote)
            .filter(RecipeNote.recipe_id == r.id)
            .order_by(RecipeNote.created_at.desc())
            .all()
        )
        recipe_data["note_count"] = len(notes)
        recipe_data["has_positive_notes"] = any(n.outcome == NoteOutcome.SUCCESS for n in notes)
        if notes:
            latest = notes[0]
            recipe_data["latest_note"] = {
                "title": latest.title,
                "outcome": latest.outcome.value if latest.outcome else None,
                "user": latest.added_by,
            }
        else:
            recipe_data["latest_note"] = None

        # Filter by tag if requested
        if params.get("tags"):
            tag_filter = params["tags"].lower()
            recipe_tags = [t.lower() for t in (r.tags or [])]
            if not any(tag_filter in t for t in recipe_tags):
                continue

        result.append(recipe_data)

    print(f"[get_recipes] SUCCESS: {len(result)} recipes", flush=True)
    return {"recipes": result, "count": len(result)}


def execute_get_meal_plan(params: dict, db_session: Session, **kwargs) -> dict:
    """Get active meal plan."""
    print("[get_meal_plan] Called", flush=True)
    plan = (
        db_session.query(MealPlan)
        .filter(MealPlan.status == MealPlanStatus.PLANNING)
        .order_by(MealPlan.created_at.desc())
        .first()
    )
    if not plan:
        print("[get_meal_plan] No active plan", flush=True)
        return {"plan": None}

    print(f"[get_meal_plan] SUCCESS: {len(plan.meals or [])} meals", flush=True)
    return {
        "plan": {
            "id": plan.id,
            "meals": plan.meals or [],
            "status": plan.status.value,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
        }
    }


def execute_get_pantry(params: dict, db_session: Session, **kwargs) -> dict:
    """Get all pantry items with ingredient info."""
    print("[get_pantry] Called", flush=True)
    items = db_session.query(PantryItem).order_by(PantryItem.item_name).all()
    result = []
    for i in items:
        item_data = {
            "item_name": i.item_name,
            "quantity": i.quantity,
            "unit": i.unit,
            "ingredient_id": i.ingredient_id,
        }
        # Include ingredient info if linked
        if i.ingredient_id and i.ingredient:
            item_data["preferred_brand"] = i.ingredient.preferred_brand
            item_data["has_kroger_mapping"] = i.ingredient.kroger_product_id is not None
        result.append(item_data)
    print(f"[get_pantry] SUCCESS: {len(result)} items", flush=True)
    return {"items": result, "count": len(result)}


def execute_get_preferences(params: dict, db_session: Session, **kwargs) -> dict:
    """Get dietary preferences."""
    print(f"[get_preferences] Called: {params}", flush=True)
    query = db_session.query(Preference)
    if params.get("user"):
        query = query.filter(Preference.user.ilike(params["user"]))
    prefs = query.all()
    result = [{"user": p.user, "data": p.data or {}} for p in prefs]
    print(f"[get_preferences] SUCCESS: {len(result)} prefs", flush=True)
    return {"preferences": result}


def execute_get_recipe_notes(params: dict, db_session: Session, **kwargs) -> dict:
    """Get recipe notes."""
    print(f"[get_recipe_notes] Called: {params}", flush=True)
    query = db_session.query(RecipeNote)
    if params.get("recipe_name"):
        normalized = normalize_recipe_name(params["recipe_name"])
        query = query.filter(RecipeNote.recipe_name_normalized.contains(normalized))
    notes = query.order_by(RecipeNote.created_at.desc()).limit(20).all()
    result = [
        {
            "recipe_name": n.recipe_name,
            "title": n.title,
            "user": n.user,
            "note_text": n.note_text,
            "note_type": n.note_type.value,
            "outcome": n.outcome.value,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notes
    ]
    print(f"[get_recipe_notes] SUCCESS: {len(result)} notes", flush=True)
    return {"notes": result, "count": len(result)}


def execute_get_order_history(params: dict, db_session: Session, **kwargs) -> dict:
    """Get past orders."""
    print(f"[get_order_history] Called: {params}", flush=True)
    limit = params.get("limit", 5)
    orders = (
        db_session.query(ShoppingList)
        .filter(ShoppingList.status == ShoppingListStatus.ORDERED)
        .order_by(ShoppingList.ordered_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for o in orders:
        item_count = (
            db_session.query(ShoppingListItem)
            .filter(ShoppingListItem.shopping_list_id == o.id)
            .count()
        )
        result.append({
            "id": o.id,
            "item_count": item_count,
            "ordered_at": o.ordered_at.isoformat() if o.ordered_at else None,
        })
    print(f"[get_order_history] SUCCESS: {len(result)} orders", flush=True)
    return {"orders": result}


# =============================================================================
# Write Tool Handlers
# =============================================================================


def execute_add_item(params: dict, db_session: Session, **kwargs) -> dict:
    """Add an item to the active shopping list."""
    print(f"[add_item] Called: name={params.get('name')}, added_by={params.get('added_by')}", flush=True)
    try:
        name = params["name"].strip()
        added_by = params["added_by"].strip()

        ingredient = _get_or_create_ingredient(name, db_session)
        active_list = _get_or_create_active_list(db_session)

        quantity = params.get("quantity", 1)
        if quantity is not None:
            try:
                quantity = float(quantity)
            except (ValueError, TypeError):
                quantity = 1

        unit = (params.get("unit") or "").strip() or None

        item = ShoppingListItem(
            shopping_list_id=active_list.id,
            ingredient_id=ingredient.id,
            quantity=quantity,
            unit=unit,
            added_by=added_by,
            added_at=datetime.utcnow(),
        )
        db_session.add(item)
        db_session.flush()

        print(f"[add_item] SUCCESS: added '{ingredient.name}' (ingredient_id={ingredient.id}, item_id={item.id})", flush=True)
        _log_event(db_session, ActionType.ADD_ITEM, f"name={name}, added_by={added_by}", f"item_id={item.id}", {"ingredient_id": ingredient.id, "item_id": item.id})
        return {
            "success": True,
            "item_id": item.id,
            "ingredient_id": ingredient.id,
            "name": ingredient.name,
            "preferred_brand": ingredient.preferred_brand,
            "kroger_product_id": ingredient.kroger_product_id,
            "has_kroger_mapping": ingredient.kroger_product_id is not None,
            "purchase_source": ingredient.purchase_source,
            "needs_kroger_resolution": (
                ingredient.kroger_product_id is None
                and ingredient.purchase_source is None  # Don't resolve non-Kroger items
            ),
        }
    except Exception as e:
        print(f"[add_item] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to add item: {str(e)}"}


def execute_remove_item(params: dict, db_session: Session, **kwargs) -> dict:
    """Remove an item from the active shopping list."""
    print(f"[remove_item] Called: name={params.get('name')}", flush=True)
    try:
        name = params["name"].strip()
        normalized = normalize_ingredient_name(name)

        active_list = _get_or_create_active_list(db_session)

        # Find matching item via ingredient
        item = (
            db_session.query(ShoppingListItem)
            .join(Ingredient)
            .filter(
                ShoppingListItem.shopping_list_id == active_list.id,
                Ingredient.normalized_name.contains(normalized),
            )
            .first()
        )

        if not item:
            print(f"[remove_item] Not found: '{name}'", flush=True)
            return {"error": f"Item '{name}' not found on the shopping list."}

        removed_name = item.ingredient.name
        db_session.delete(item)
        print(f"[remove_item] SUCCESS: removed '{removed_name}'", flush=True)
        _log_event(db_session, ActionType.REMOVE_ITEM, f"name={name}", f"removed={removed_name}")
        return {"success": True, "removed": removed_name}
    except Exception as e:
        print(f"[remove_item] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to remove item: {str(e)}"}


def execute_update_item(params: dict, db_session: Session, **kwargs) -> dict:
    """Update quantity or unit of an existing shopping list item."""
    print(f"[update_item] Called: item_name={params.get('item_name')}", flush=True)
    try:
        item_name = params["item_name"].strip()
        normalized = normalize_ingredient_name(item_name)

        active_list = _get_or_create_active_list(db_session)

        # Find matching item via ingredient (same pattern as remove_item)
        item = (
            db_session.query(ShoppingListItem)
            .join(Ingredient)
            .filter(
                ShoppingListItem.shopping_list_id == active_list.id,
                Ingredient.normalized_name.contains(normalized),
            )
            .first()
        )

        if not item:
            print(f"[update_item] Not found: '{item_name}'", flush=True)
            return {"error": f"Item '{item_name}' not found on the shopping list."}

        # Update quantity if provided
        if params.get("quantity") is not None:
            try:
                item.quantity = float(params["quantity"])
            except (ValueError, TypeError):
                pass

        # Update unit if provided
        if params.get("unit"):
            item.unit = params["unit"].strip()

        print(f"[update_item] SUCCESS: updated '{item.ingredient.name}' to quantity={item.quantity}, unit={item.unit}", flush=True)
        _log_event(db_session, ActionType.REMOVE_ITEM, f"name={item_name}", f"updated quantity/unit")
        return {
            "success": True,
            "item_id": item.id,
            "name": item.ingredient.name,
            "quantity": item.quantity,
            "unit": item.unit,
        }
    except Exception as e:
        print(f"[update_item] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to update item: {str(e)}"}


def execute_clear_list(params: dict, db_session: Session, **kwargs) -> dict:
    """Clear all items from the active shopping list."""
    print("[clear_list] Called", flush=True)
    try:
        active_list = _get_or_create_active_list(db_session)
        count = (
            db_session.query(ShoppingListItem)
            .filter(ShoppingListItem.shopping_list_id == active_list.id)
            .delete()
        )
        print(f"[clear_list] SUCCESS: removed {count} items", flush=True)
        _log_event(db_session, ActionType.CLEAR_LIST, "clear_list", f"removed={count}")
        return {"success": True, "items_removed": count}
    except Exception as e:
        print(f"[clear_list] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to clear list: {str(e)}"}


def execute_finalize_order(params: dict, db_session: Session, **kwargs) -> dict:
    """Archive current list and create a new one."""
    print("[finalize_order] Called", flush=True)
    try:
        active_list = _get_or_create_active_list(db_session)

        item_count = (
            db_session.query(ShoppingListItem)
            .filter(ShoppingListItem.shopping_list_id == active_list.id)
            .count()
        )

        if item_count == 0:
            print("[finalize_order] Empty list, cannot finalize", flush=True)
            return {"error": "Shopping list is empty - nothing to order."}

        active_list.status = ShoppingListStatus.ORDERED
        active_list.ordered_at = datetime.utcnow()

        new_list = ShoppingList(status=ShoppingListStatus.ACTIVE)
        db_session.add(new_list)
        db_session.flush()

        print(f"[finalize_order] SUCCESS: archived {item_count} items, new list id={new_list.id}", flush=True)
        _log_event(db_session, ActionType.FINALIZE_ORDER, f"items={item_count}", f"new_list_id={new_list.id}", {"new_list_id": new_list.id})
        return {"success": True, "items_ordered": item_count, "new_list_id": new_list.id}
    except Exception as e:
        print(f"[finalize_order] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to finalize order: {str(e)}"}


def execute_update_ingredient(params: dict, db_session: Session, **kwargs) -> dict:
    """Update an ingredient's brand, size, or category."""
    print(f"[update_ingredient] Called: {params}", flush=True)
    try:
        name = params["name"].strip()
        ingredient = _get_or_create_ingredient(name, db_session)

        if params.get("preferred_brand"):
            ingredient.preferred_brand = params["preferred_brand"].strip()
        if params.get("preferred_size"):
            ingredient.preferred_size = params["preferred_size"].strip()
        if params.get("category"):
            ingredient.category = params["category"].strip()

        ingredient.updated_at = datetime.utcnow()

        print(f"[update_ingredient] SUCCESS: updated '{ingredient.name}' (id={ingredient.id})", flush=True)
        _log_event(db_session, ActionType.UPDATE_INGREDIENT, f"name={name}", f"ingredient_id={ingredient.id}", {"ingredient_id": ingredient.id})
        return {
            "success": True,
            "ingredient_id": ingredient.id,
            "name": ingredient.name,
            "preferred_brand": ingredient.preferred_brand,
            "preferred_size": ingredient.preferred_size,
            "category": ingredient.category,
        }
    except Exception as e:
        print(f"[update_ingredient] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to update ingredient: {str(e)}"}


def execute_add_recipe_note(params: dict, db_session: Session, **kwargs) -> dict:
    """Add a recipe note."""
    print(f"[add_recipe_note] Called: recipe={params.get('recipe_name')}", flush=True)
    try:
        recipe_name = params["recipe_name"].strip()
        user = params["user"].strip()
        note_text = params["note_text"].strip()
        title = (params.get("title") or "").strip() or None

        note_type_str = params.get("note_type", "general").lower()
        note_type_map = {
            "ingredient_change": NoteType.INGREDIENT_CHANGE,
            "technique": NoteType.TECHNIQUE,
            "timing": NoteType.TIMING,
            "general": NoteType.GENERAL,
        }
        note_type = note_type_map.get(note_type_str, NoteType.GENERAL)

        outcome_str = params.get("outcome", "neutral").lower()
        outcome_map = {
            "better": NoteOutcome.BETTER,
            "worse": NoteOutcome.WORSE,
            "neutral": NoteOutcome.NEUTRAL,
        }
        outcome = outcome_map.get(outcome_str, NoteOutcome.NEUTRAL)

        # Try to link to existing recipe
        recipe = (
            db_session.query(Recipe)
            .filter(Recipe.name.ilike(f"%{recipe_name}%"))
            .first()
        )

        note = RecipeNote(
            recipe_id=recipe.id if recipe else None,
            recipe_name=recipe_name,
            user=user,
            note_text=note_text,
            title=title,
            note_type=note_type,
            outcome=outcome,
        )
        db_session.add(note)
        db_session.flush()

        print(f"[add_recipe_note] SUCCESS: note id={note.id} for '{recipe_name}'", flush=True)
        _log_event(db_session, ActionType.ADD_RECIPE_NOTE, f"recipe={recipe_name}, user={user}", f"note_id={note.id}", {"note_id": note.id})
        return {"success": True, "note_id": note.id, "recipe_name": recipe_name}
    except Exception as e:
        print(f"[add_recipe_note] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to add recipe note: {str(e)}"}


def execute_add_recipe(params: dict, db_session: Session, **kwargs) -> dict:
    """Add a recipe with structured ingredients via RecipeIngredient junction."""
    print(f"[add_recipe] Called: name={params.get('name')}", flush=True)
    try:
        name = params["name"].strip()
        ingredients_data = params.get("ingredients", [])
        instructions = (params.get("instructions") or "").strip() or None
        cuisine = (params.get("cuisine") or "").strip() or None
        tags = params.get("tags")

        recipe = Recipe(
            name=name,
            instructions=instructions,
            cuisine=cuisine,
            tags=tags,
        )
        db_session.add(recipe)
        db_session.flush()

        # Auto-link ingredients
        new_ingredients = []
        for ing_data in ingredients_data:
            ing_name = ing_data.get("name", "").strip()
            if not ing_name:
                continue

            ingredient = _get_or_create_ingredient(ing_name, db_session)

            ri = RecipeIngredient(
                recipe_id=recipe.id,
                ingredient_id=ingredient.id,
                quantity=ing_data.get("quantity"),
                unit=(ing_data.get("unit") or "").strip() or None,
                prep_notes=(ing_data.get("prep_notes") or "").strip() or None,
            )
            db_session.add(ri)
            new_ingredients.append({
                "name": ingredient.name,
                "ingredient_id": ingredient.id,
                "has_kroger_mapping": ingredient.kroger_product_id is not None,
            })

        db_session.flush()

        # Identify ingredients without Kroger mapping
        unmapped = [i for i in new_ingredients if not i["has_kroger_mapping"]]

        # Backfill orphaned notes that were created before this recipe
        notes_linked = _backfill_orphaned_notes(recipe, db_session)

        print(f"[add_recipe] SUCCESS: recipe id={recipe.id}, {len(new_ingredients)} ingredients, {len(unmapped)} unmapped, {notes_linked} notes linked", flush=True)
        _log_event(db_session, ActionType.ADD_RECIPE, f"name={name}, ingredients={len(new_ingredients)}", f"recipe_id={recipe.id}", {"recipe_id": recipe.id})
        return {
            "success": True,
            "recipe_id": recipe.id,
            "name": name,
            "ingredient_count": len(new_ingredients),
            "ingredients": new_ingredients,
            "unmapped_ingredients": [i["name"] for i in unmapped],
            "notes_linked": notes_linked,
        }
    except Exception as e:
        print(f"[add_recipe] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to add recipe: {str(e)}"}


def execute_add_meal(params: dict, db_session: Session, **kwargs) -> dict:
    """Add a meal to the active meal plan."""
    print(f"[add_meal] Called: {params.get('meal_name')}", flush=True)
    try:
        plan = _get_or_create_active_meal_plan(db_session)

        meal_entry = {
            "meal_name": params["meal_name"].strip(),
            "added_at": datetime.utcnow().isoformat(),
        }

        if params.get("recipe_id"):
            try:
                meal_entry["recipe_id"] = int(params["recipe_id"])
            except (ValueError, TypeError):
                pass

        if params.get("notes"):
            meal_entry["notes"] = params["notes"].strip()

        if plan.meals is None:
            plan.meals = []
        plan.meals = plan.meals + [meal_entry]

        print(f"[add_meal] SUCCESS: added '{meal_entry['meal_name']}' to plan {plan.id}", flush=True)
        _log_event(db_session, ActionType.ADD_MEAL, f"meal={meal_entry['meal_name']}", f"plan_id={plan.id}", {"plan_id": plan.id})
        return {"success": True, "meal_name": meal_entry["meal_name"], "plan_id": plan.id}
    except Exception as e:
        print(f"[add_meal] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to add meal: {str(e)}"}


def execute_remove_meal(params: dict, db_session: Session, **kwargs) -> dict:
    """Remove a meal from the active meal plan."""
    print(f"[remove_meal] Called: {params.get('meal_name')}", flush=True)
    try:
        plan = (
            db_session.query(MealPlan)
            .filter(MealPlan.status == MealPlanStatus.PLANNING)
            .order_by(MealPlan.created_at.desc())
            .first()
        )
        if not plan or not plan.meals:
            return {"error": "No active meal plan or no meals to remove."}

        meal_name = params["meal_name"].strip().lower()
        remaining = [m for m in plan.meals if m.get("meal_name", "").lower() != meal_name]

        if len(remaining) == len(plan.meals):
            print(f"[remove_meal] Not found: '{params['meal_name']}'", flush=True)
            return {"error": f"Meal '{params['meal_name']}' not found in the plan."}

        plan.meals = remaining
        print(f"[remove_meal] SUCCESS: removed '{params['meal_name']}'", flush=True)
        _log_event(db_session, ActionType.REMOVE_MEAL, f"meal={params['meal_name']}", "removed")
        return {"success": True, "removed": params["meal_name"]}
    except Exception as e:
        print(f"[remove_meal] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to remove meal: {str(e)}"}


def execute_generate_list_from_meals(params: dict, db_session: Session, **kwargs) -> dict:
    """Generate shopping list items from planned meals."""
    print("[generate_list_from_meals] Called", flush=True)
    try:
        plan = (
            db_session.query(MealPlan)
            .filter(MealPlan.status == MealPlanStatus.PLANNING)
            .order_by(MealPlan.created_at.desc())
            .first()
        )
        if not plan or not plan.meals:
            return {"error": "No active meal plan or no meals planned."}

        active_list = _get_or_create_active_list(db_session)

        # Build set of existing ingredient IDs on the list for dedup
        existing_ids = set(
            row[0]
            for row in db_session.query(ShoppingListItem.ingredient_id)
            .filter(ShoppingListItem.shopping_list_id == active_list.id)
            .all()
        )

        # Get pantry item names for cross-reference
        pantry_names = set(
            normalize_ingredient_name(p.item_name)
            for p in db_session.query(PantryItem).all()
        )

        items_added = 0
        skipped_pantry = []
        skipped_existing = []

        for meal in plan.meals:
            recipe_id = meal.get("recipe_id")
            if not recipe_id:
                continue

            recipe_ings = (
                db_session.query(RecipeIngredient)
                .filter(RecipeIngredient.recipe_id == recipe_id)
                .all()
            )

            for ri in recipe_ings:
                # Skip if already on list
                if ri.ingredient_id in existing_ids:
                    skipped_existing.append(ri.ingredient.name)
                    continue

                # Skip if in pantry
                if ri.ingredient.normalized_name in pantry_names:
                    skipped_pantry.append(ri.ingredient.name)
                    continue

                item = ShoppingListItem(
                    shopping_list_id=active_list.id,
                    ingredient_id=ri.ingredient_id,
                    quantity=ri.quantity,
                    unit=ri.unit,
                    added_by="meal plan",
                    added_at=datetime.utcnow(),
                    from_recipe_id=recipe_id,
                )
                db_session.add(item)
                existing_ids.add(ri.ingredient_id)
                items_added += 1

        print(f"[generate_list_from_meals] SUCCESS: added {items_added}, skipped {len(skipped_existing)} existing, {len(skipped_pantry)} pantry", flush=True)
        _log_event(db_session, ActionType.GENERATE_LIST, f"meals={len(plan.meals)}", f"added={items_added}")
        return {
            "success": True,
            "items_added": items_added,
            "skipped_existing": skipped_existing,
            "skipped_pantry": skipped_pantry,
        }
    except Exception as e:
        print(f"[generate_list_from_meals] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to generate list: {str(e)}"}


def execute_complete_meal_plan(params: dict, db_session: Session, **kwargs) -> dict:
    """Mark active meal plan as completed."""
    print("[complete_meal_plan] Called", flush=True)
    try:
        plan = (
            db_session.query(MealPlan)
            .filter(MealPlan.status == MealPlanStatus.PLANNING)
            .order_by(MealPlan.created_at.desc())
            .first()
        )
        if not plan:
            return {"error": "No active meal plan to complete."}

        plan.status = MealPlanStatus.COMPLETED
        plan.updated_at = datetime.utcnow()
        print(f"[complete_meal_plan] SUCCESS: completed plan {plan.id}", flush=True)
        _log_event(db_session, ActionType.COMPLETE_MEAL_PLAN, f"plan_id={plan.id}", "completed", {"plan_id": plan.id})
        return {"success": True, "plan_id": plan.id}
    except Exception as e:
        print(f"[complete_meal_plan] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to complete meal plan: {str(e)}"}


def execute_update_preference(params: dict, db_session: Session, **kwargs) -> dict:
    """Update a user dietary preference."""
    print(f"[update_preference] Called: {params}", flush=True)
    try:
        user = params["user"].strip().capitalize()
        category = params["category"].strip().lower()
        value = params["value"].strip()

        pref = db_session.query(Preference).filter(Preference.user == user).first()
        if not pref:
            pref = Preference(user=user, data={})
            db_session.add(pref)
            db_session.flush()

        pref_data = pref.data or {}

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
        pref.updated_at = datetime.utcnow()

        print(f"[update_preference] SUCCESS: {user}.{category} = {value}", flush=True)
        _log_event(db_session, ActionType.UPDATE_PREFERENCE, f"{user}.{category}={value}", "updated")
        return {"success": True, "user": user, "category": category, "value": value}
    except Exception as e:
        print(f"[update_preference] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to update preference: {str(e)}"}


def execute_add_pantry_item(params: dict, db_session: Session, **kwargs) -> dict:
    """Add or upsert a pantry item, auto-linking to ingredient record."""
    print(f"[add_pantry_item] Called: {params.get('item_name')}", flush=True)
    try:
        item_name = params["item_name"].strip()

        # Get or create ingredient record and link to pantry item
        ingredient = _get_or_create_ingredient(item_name, db_session)

        existing = (
            db_session.query(PantryItem)
            .filter(PantryItem.item_name.ilike(item_name))
            .first()
        )

        quantity = None
        if params.get("quantity") is not None:
            try:
                quantity = float(params["quantity"])
            except (ValueError, TypeError):
                pass

        unit = (params.get("unit") or "").strip() or None

        if existing:
            if quantity is not None:
                existing.quantity = quantity
            if unit:
                existing.unit = unit
            # Ensure ingredient link exists
            if not existing.ingredient_id:
                existing.ingredient_id = ingredient.id
            existing.updated_at = datetime.utcnow()
            print(f"[add_pantry_item] SUCCESS: updated '{item_name}' (ingredient_id={ingredient.id})", flush=True)
            _log_event(db_session, ActionType.ADD_PANTRY_ITEM, f"name={item_name}", "updated")
            return {"success": True, "item_name": item_name, "action": "updated", "ingredient_id": ingredient.id}
        else:
            new_item = PantryItem(item_name=item_name, quantity=quantity, unit=unit, ingredient_id=ingredient.id)
            db_session.add(new_item)
            print(f"[add_pantry_item] SUCCESS: added '{item_name}' (ingredient_id={ingredient.id})", flush=True)
            _log_event(db_session, ActionType.ADD_PANTRY_ITEM, f"name={item_name}", "added")
            return {"success": True, "item_name": item_name, "action": "added", "ingredient_id": ingredient.id}
    except Exception as e:
        print(f"[add_pantry_item] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to add pantry item: {str(e)}"}


def execute_add_pantry_batch(params: dict, db_session: Session, **kwargs) -> dict:
    """Add multiple pantry items at once."""
    print(f"[add_pantry_batch] Called with {len(params.get('items', []))} items", flush=True)
    try:
        items = params.get("items", [])
        if not items:
            return {"error": "No items provided."}

        added = []
        updated = []

        for item_data in items:
            item_name = item_data.get("item_name", "").strip()
            if not item_name:
                continue

            # Get or create ingredient record
            ingredient = _get_or_create_ingredient(item_name, db_session)

            # Parse quantity
            quantity = None
            if item_data.get("quantity") is not None:
                try:
                    quantity = float(item_data["quantity"])
                except (ValueError, TypeError):
                    pass

            unit = (item_data.get("unit") or "").strip() or None

            # Check if pantry item exists
            existing = (
                db_session.query(PantryItem)
                .filter(PantryItem.item_name.ilike(item_name))
                .first()
            )

            if existing:
                if quantity is not None:
                    existing.quantity = quantity
                if unit:
                    existing.unit = unit
                if not existing.ingredient_id:
                    existing.ingredient_id = ingredient.id
                existing.updated_at = datetime.utcnow()
                updated.append(item_name)
            else:
                new_item = PantryItem(
                    item_name=item_name,
                    quantity=quantity,
                    unit=unit,
                    ingredient_id=ingredient.id,
                )
                db_session.add(new_item)
                added.append(item_name)

        _log_event(db_session, ActionType.ADD_PANTRY_ITEM, f"batch={len(items)}", f"added={len(added)}, updated={len(updated)}")
        print(f"[add_pantry_batch] SUCCESS: added={added}, updated={updated}", flush=True)
        return {
            "success": True,
            "added": added,
            "updated": updated,
            "count": len(added) + len(updated),
        }
    except Exception as e:
        print(f"[add_pantry_batch] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to add pantry items: {str(e)}"}


def execute_update_pantry_item(params: dict, db_session: Session, **kwargs) -> dict:
    """Update an existing pantry item."""
    print(f"[update_pantry_item] Called: {params.get('item_name')}", flush=True)
    try:
        item_name = params["item_name"].strip()
        existing = (
            db_session.query(PantryItem)
            .filter(PantryItem.item_name.ilike(item_name))
            .first()
        )

        if not existing:
            return {"error": f"Pantry item '{item_name}' not found."}

        if params.get("quantity") is not None:
            try:
                existing.quantity = float(params["quantity"])
            except (ValueError, TypeError):
                pass

        if params.get("unit"):
            existing.unit = params["unit"].strip()

        existing.updated_at = datetime.utcnow()
        print(f"[update_pantry_item] SUCCESS: updated '{item_name}'", flush=True)
        _log_event(db_session, ActionType.UPDATE_PANTRY_ITEM, f"name={item_name}", "updated")
        return {"success": True, "item_name": item_name}
    except Exception as e:
        print(f"[update_pantry_item] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to update pantry item: {str(e)}"}


def execute_remove_pantry_item(params: dict, db_session: Session, **kwargs) -> dict:
    """Remove a pantry item."""
    print(f"[remove_pantry_item] Called: {params.get('item_name')}", flush=True)
    try:
        item_name = params["item_name"].strip()
        existing = (
            db_session.query(PantryItem)
            .filter(PantryItem.item_name.ilike(item_name))
            .first()
        )

        if not existing:
            return {"error": f"Pantry item '{item_name}' not found."}

        db_session.delete(existing)
        print(f"[remove_pantry_item] SUCCESS: removed '{item_name}'", flush=True)
        _log_event(db_session, ActionType.REMOVE_PANTRY_ITEM, f"name={item_name}", "removed")
        return {"success": True, "removed": item_name}
    except Exception as e:
        print(f"[remove_pantry_item] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to remove pantry item: {str(e)}"}


def execute_resolve_kroger_product(params: dict, db_session: Session, **kwargs) -> dict:
    """Search Kroger for a product."""
    print(f"[resolve_kroger_product] Called: {params.get('ingredient_name')}", flush=True)
    try:
        from .kroger_service import search_products, is_configured

        if not is_configured():
            return {"error": "Kroger integration is not configured."}

        ingredient_name = params["ingredient_name"].strip()
        brand_hint = (params.get("brand_hint") or "").strip() or None

        # Filter out common non-brand words that Claude sometimes passes as brand hints
        # These are product attributes, not actual brands
        non_brand_words = {
            "organic", "fresh", "frozen", "dried", "canned", "whole", "raw",
            "natural", "pure", "low", "fat", "free", "reduced", "light",
        }
        if brand_hint and brand_hint.lower() in non_brand_words:
            print(f"[resolve_kroger_product] Filtering out non-brand hint: '{brand_hint}'", flush=True)
            brand_hint = None

        results = search_products(ingredient_name, brand=brand_hint, limit=5)
        print(f"[resolve_kroger_product] SUCCESS: {len(results)} results for '{ingredient_name}'", flush=True)
        _log_event(db_session, ActionType.RESOLVE_KROGER, f"ingredient={ingredient_name}", f"results={len(results)}")
        return {"results": results, "ingredient_name": ingredient_name}
    except Exception as e:
        print(f"[resolve_kroger_product] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Kroger search failed: {str(e)}"}


def execute_confirm_kroger_product(params: dict, db_session: Session, **kwargs) -> dict:
    """Confirm a Kroger product and store mapping on Ingredient."""
    print(f"[confirm_kroger_product] Called: {params.get('ingredient_name')}", flush=True)
    try:
        ingredient_name = params["ingredient_name"].strip()
        kroger_product_id = params["kroger_product_id"].strip()
        brand = (params.get("brand") or "").strip() or None
        size = (params.get("size") or "").strip() or None
        price = params.get("price")

        ingredient = _get_or_create_ingredient(ingredient_name, db_session)
        ingredient.kroger_product_id = kroger_product_id
        if brand:
            ingredient.preferred_brand = brand
        if size:
            ingredient.preferred_size = size
        if price is not None:
            try:
                ingredient.last_known_price = float(price)
            except (ValueError, TypeError):
                pass
        ingredient.updated_at = datetime.utcnow()

        print(f"[confirm_kroger_product] SUCCESS: '{ingredient.name}' -> {kroger_product_id} @ ${ingredient.last_known_price}", flush=True)
        _log_event(db_session, ActionType.CONFIRM_KROGER, f"ingredient={ingredient_name}, product={kroger_product_id}", f"ingredient_id={ingredient.id}", {"ingredient_id": ingredient.id})
        return {
            "success": True,
            "ingredient_id": ingredient.id,
            "name": ingredient.name,
            "kroger_product_id": kroger_product_id,
            "brand": ingredient.preferred_brand,
            "size": ingredient.preferred_size,
            "price": ingredient.last_known_price,
        }
    except Exception as e:
        print(f"[confirm_kroger_product] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to confirm Kroger product: {str(e)}"}


def execute_add_to_kroger_cart(params: dict, db_session: Session, **kwargs) -> dict:
    """Add all resolved shopping list items to Kroger cart."""
    print("[add_to_kroger_cart] Called", flush=True)
    try:
        from .kroger_service import add_items_to_cart, is_user_authenticated, is_configured, get_auth_url

        if not is_configured():
            return {"error": "Kroger integration is not configured."}

        if not is_user_authenticated():
            auth_url = get_auth_url()
            return {"error": "not_authenticated", "auth_url": auth_url}

        active_list = _get_or_create_active_list(db_session)
        items = (
            db_session.query(ShoppingListItem)
            .join(Ingredient)
            .filter(ShoppingListItem.shopping_list_id == active_list.id)
            .all()
        )

        if not items:
            return {"error": "Shopping list is empty."}

        resolved = []
        unresolved = []
        skipped_non_kroger = []
        for item in items:
            # Skip non-Kroger items (they have a purchase_source set)
            if item.ingredient.purchase_source:
                skipped_non_kroger.append({
                    "name": item.ingredient.name,
                    "source": item.ingredient.purchase_source,
                })
                continue
            if item.ingredient.kroger_product_id:
                resolved.append({
                    "upc": item.ingredient.kroger_product_id,
                    "quantity": int(item.quantity or 1),
                })
            else:
                unresolved.append(item.ingredient.name)

        if unresolved:
            return {
                "error": "unresolved_items",
                "unresolved": unresolved,
                "resolved_count": len(resolved),
            }

        success = add_items_to_cart(resolved)
        if success:
            # Archive the list after successful cart add
            active_list.status = ShoppingListStatus.ORDERED
            active_list.ordered_at = datetime.utcnow()
            print(f"[add_to_kroger_cart] SUCCESS: {len(resolved)} items, skipped {len(skipped_non_kroger)} non-Kroger. List archived.", flush=True)
            _log_event(db_session, ActionType.ADD_TO_CART, f"items={len(resolved)}", "success, list archived")
            result = {"success": True, "items_added": len(resolved), "list_archived": True}
            if skipped_non_kroger:
                result["skipped_non_kroger"] = skipped_non_kroger
            return result
        else:
            return {"error": "Failed to add items to Kroger cart."}
    except Exception as e:
        print(f"[add_to_kroger_cart] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Kroger cart error: {str(e)}"}


def execute_check_off_item(params: dict, db_session: Session, **kwargs) -> dict:
    """Toggle checked_off on a shopping list item."""
    print(f"[check_off_item] Called: {params.get('name')}", flush=True)
    try:
        name = params["name"].strip()
        normalized = normalize_ingredient_name(name)

        active_list = _get_or_create_active_list(db_session)
        item = (
            db_session.query(ShoppingListItem)
            .join(Ingredient)
            .filter(
                ShoppingListItem.shopping_list_id == active_list.id,
                Ingredient.normalized_name.contains(normalized),
            )
            .first()
        )

        if not item:
            return {"error": f"Item '{name}' not found on the shopping list."}

        item.checked_off = not item.checked_off
        status = "checked off" if item.checked_off else "unchecked"
        print(f"[check_off_item] SUCCESS: '{item.ingredient.name}' {status}", flush=True)
        _log_event(db_session, ActionType.CHECK_OFF_ITEM, f"name={name}", status)
        return {"success": True, "name": item.ingredient.name, "checked_off": item.checked_off}
    except Exception as e:
        print(f"[check_off_item] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to check off item: {str(e)}"}


# =============================================================================
# Batch Operations
# =============================================================================


def execute_import_recipes_batch(params: dict, db_session: Session, **kwargs) -> dict:
    """Import multiple recipes in a single transaction."""
    print(f"[import_recipes_batch] Called: {len(params.get('recipes', []))} recipes", flush=True)
    try:
        recipes_data = params.get("recipes", [])
        if not recipes_data:
            return {"error": "No recipes provided."}

        recipes_created = []
        ingredients_created = []
        ingredients_needing_kroger = []
        seen_ingredient_ids = set()

        for recipe_data in recipes_data:
            name = recipe_data.get("name", "").strip()
            if not name:
                continue

            ingredients_list = recipe_data.get("ingredients", [])
            instructions = (recipe_data.get("instructions") or "").strip() or None
            cuisine = (recipe_data.get("cuisine") or "").strip() or None
            tags = recipe_data.get("tags")

            # Create recipe
            recipe = Recipe(
                name=name,
                instructions=instructions,
                cuisine=cuisine,
                tags=tags,
            )
            db_session.add(recipe)
            db_session.flush()

            recipe_ings = []
            for ing_data in ingredients_list:
                ing_name = ing_data.get("name", "").strip()
                if not ing_name:
                    continue

                ingredient = _get_or_create_ingredient(ing_name, db_session)

                ri = RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=ingredient.id,
                    quantity=ing_data.get("quantity"),
                    unit=(ing_data.get("unit") or "").strip() or None,
                    prep_notes=(ing_data.get("prep_notes") or "").strip() or None,
                )
                db_session.add(ri)
                recipe_ings.append(ingredient.name)

                # Track unique ingredients
                if ingredient.id not in seen_ingredient_ids:
                    seen_ingredient_ids.add(ingredient.id)
                    ingredients_created.append(ingredient.name)
                    if not ingredient.kroger_product_id:
                        ingredients_needing_kroger.append(ingredient.name)

            # Backfill orphaned notes
            notes_linked = _backfill_orphaned_notes(recipe, db_session)

            recipes_created.append({
                "name": name,
                "id": recipe.id,
                "ingredient_count": len(recipe_ings),
                "notes_linked": notes_linked,
            })

        db_session.flush()

        print(f"[import_recipes_batch] SUCCESS: {len(recipes_created)} recipes, {len(ingredients_created)} unique ingredients, {len(ingredients_needing_kroger)} need Kroger", flush=True)
        _log_event(db_session, ActionType.ADD_RECIPE, f"batch import: {len(recipes_created)} recipes", f"ingredients={len(ingredients_created)}")
        return {
            "success": True,
            "recipes_created": recipes_created,
            "ingredients_created": ingredients_created,
            "ingredients_needing_kroger": ingredients_needing_kroger,
            "summary": {
                "recipe_count": len(recipes_created),
                "ingredient_count": len(ingredients_created),
                "needing_kroger_count": len(ingredients_needing_kroger),
            },
        }
    except Exception as e:
        print(f"[import_recipes_batch] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to import recipes: {str(e)}"}


def execute_match_purchases_to_ingredients(params: dict, db_session: Session, **kwargs) -> dict:
    """Fetch Kroger purchase history and fuzzy match to ingredients missing Kroger IDs."""
    print("[match_purchases_to_ingredients] Called", flush=True)
    try:
        from .kroger_service import get_purchase_history, is_user_authenticated, is_configured, get_auth_url
        from difflib import SequenceMatcher

        if not is_configured():
            return {"error": "Kroger integration is not configured."}

        if not is_user_authenticated():
            auth_url = get_auth_url()
            return {"error": "not_authenticated", "auth_url": auth_url, "message": "Visit the auth URL to connect your Kroger account and enable purchase history."}

        # Fetch purchase history
        purchases = get_purchase_history(limit=100)
        if not purchases:
            return {"error": "No purchase history available. You may need to re-authorize with the profile.compact scope."}

        # Get all ingredients without Kroger IDs
        unmapped_ingredients = (
            db_session.query(Ingredient)
            .filter(Ingredient.kroger_product_id.is_(None))
            .all()
        )

        if not unmapped_ingredients:
            return {"message": "All ingredients already have Kroger mappings!", "matches": [], "unmatched_ingredients": []}

        # Build normalized name -> ingredient map
        ingredient_map = {ing.normalized_name: ing for ing in unmapped_ingredients}

        matches = []
        matched_ingredient_ids = set()

        for purchase in purchases:
            purchase_desc = purchase.get("description", "").lower()
            purchase_brand = purchase.get("brand", "")
            purchase_id = purchase.get("productId") or purchase.get("upc", "")

            if not purchase_id:
                continue

            # Try to match against each unmapped ingredient
            for normalized_name, ingredient in ingredient_map.items():
                if ingredient.id in matched_ingredient_ids:
                    continue

                # Calculate similarity
                ratio = SequenceMatcher(None, normalized_name, purchase_desc).ratio()

                # Also check if ingredient name appears in purchase description
                name_in_desc = normalized_name in purchase_desc or any(
                    word in purchase_desc for word in normalized_name.split() if len(word) > 3
                )

                confidence = ratio
                if name_in_desc:
                    confidence = max(confidence, 0.7)

                if confidence >= 0.5:
                    matches.append({
                        "ingredient": ingredient.name,
                        "ingredient_id": ingredient.id,
                        "purchase": purchase.get("description", ""),
                        "brand": purchase_brand,
                        "productId": purchase_id,
                        "size": purchase.get("size", ""),
                        "confidence": round(confidence, 2),
                    })
                    matched_ingredient_ids.add(ingredient.id)

        # Sort by confidence
        matches.sort(key=lambda x: x["confidence"], reverse=True)

        # Find unmatched ingredients
        unmatched = [ing.name for ing in unmapped_ingredients if ing.id not in matched_ingredient_ids]

        print(f"[match_purchases_to_ingredients] SUCCESS: {len(matches)} matches, {len(unmatched)} unmatched", flush=True)
        return {
            "matches": matches,
            "unmatched_ingredients": unmatched,
            "summary": {
                "total_ingredients": len(unmapped_ingredients),
                "matched": len(matches),
                "unmatched": len(unmatched),
            },
        }
    except Exception as e:
        print(f"[match_purchases_to_ingredients] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to match purchases: {str(e)}"}


def execute_update_recipe(params: dict, db_session: Session, **kwargs) -> dict:
    """Update an existing recipe - add/remove ingredients or update description."""
    print(f"[update_recipe] Called: recipe_name={params.get('recipe_name')}", flush=True)
    try:
        recipe_name = params["recipe_name"].strip()

        # Find the recipe
        recipe = (
            db_session.query(Recipe)
            .filter(Recipe.name.ilike(f"%{recipe_name}%"))
            .first()
        )

        if not recipe:
            return {"error": f"Recipe '{recipe_name}' not found."}

        changes = []

        # Update description
        if params.get("update_description"):
            recipe.description = params["update_description"].strip()
            changes.append("description updated")

        # Remove ingredients
        remove_list = params.get("remove_ingredients", [])
        removed = []
        for ing_name in remove_list:
            normalized = normalize_ingredient_name(ing_name)
            ri = (
                db_session.query(RecipeIngredient)
                .join(Ingredient)
                .filter(
                    RecipeIngredient.recipe_id == recipe.id,
                    Ingredient.normalized_name.contains(normalized),
                )
                .first()
            )
            if ri:
                removed.append(ri.ingredient.name)
                db_session.delete(ri)

        if removed:
            changes.append(f"removed: {', '.join(removed)}")

        # Add ingredients
        add_list = params.get("add_ingredients", [])
        added = []
        for ing_data in add_list:
            ing_name = ing_data.get("name", "").strip()
            if not ing_name:
                continue

            ingredient = _get_or_create_ingredient(ing_name, db_session)

            # Check if already linked
            existing = (
                db_session.query(RecipeIngredient)
                .filter(
                    RecipeIngredient.recipe_id == recipe.id,
                    RecipeIngredient.ingredient_id == ingredient.id,
                )
                .first()
            )

            if not existing:
                ri = RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=ingredient.id,
                    quantity=ing_data.get("quantity"),
                    unit=(ing_data.get("unit") or "").strip() or None,
                    prep_notes=(ing_data.get("prep_notes") or "").strip() or None,
                )
                db_session.add(ri)
                added.append(ingredient.name)

        if added:
            changes.append(f"added: {', '.join(added)}")

        if not changes:
            return {"message": "No changes made.", "recipe_name": recipe.name}

        recipe.updated_at = datetime.utcnow()
        db_session.flush()

        # Get current ingredient list
        current_ings = (
            db_session.query(RecipeIngredient)
            .filter(RecipeIngredient.recipe_id == recipe.id)
            .all()
        )
        current_ingredients = [
            {
                "name": ri.ingredient.name,
                "quantity": ri.quantity,
                "unit": ri.unit,
            }
            for ri in current_ings
        ]

        print(f"[update_recipe] SUCCESS: {recipe.name} - {', '.join(changes)}", flush=True)
        _log_event(db_session, ActionType.UPDATE_INGREDIENT, f"recipe={recipe.name}", f"changes: {', '.join(changes)}", {"recipe_id": recipe.id})
        return {
            "success": True,
            "recipe_id": recipe.id,
            "recipe_name": recipe.name,
            "changes": changes,
            "current_ingredients": current_ingredients,
        }
    except Exception as e:
        print(f"[update_recipe] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to update recipe: {str(e)}"}


def execute_set_ingredient_alias(params: dict, db_session: Session, **kwargs) -> dict:
    """Add an alias for an ingredient."""
    print(f"[set_ingredient_alias] Called: {params.get('ingredient_name')} -> {params.get('alias')}", flush=True)
    try:
        ingredient_name = params["ingredient_name"].strip()
        alias = params["alias"].strip()

        if not alias:
            return {"error": "Alias cannot be empty."}

        # Find the ingredient
        normalized = normalize_ingredient_name(ingredient_name)
        ingredient = (
            db_session.query(Ingredient)
            .filter(Ingredient.normalized_name == normalized)
            .first()
        )

        if not ingredient:
            return {"error": f"Ingredient '{ingredient_name}' not found. Add it first before setting aliases."}

        # Add alias to the list
        normalized_alias = normalize_ingredient_name(alias)
        current_aliases = ingredient.aliases or []

        if normalized_alias in [normalize_ingredient_name(a) for a in current_aliases]:
            return {"message": f"Alias '{alias}' already exists for '{ingredient.name}'.", "ingredient_name": ingredient.name}

        current_aliases.append(alias)
        ingredient.aliases = current_aliases
        ingredient.updated_at = datetime.utcnow()

        print(f"[set_ingredient_alias] SUCCESS: '{alias}' -> '{ingredient.name}'", flush=True)
        return {
            "success": True,
            "ingredient_name": ingredient.name,
            "alias_added": alias,
            "all_aliases": ingredient.aliases,
        }
    except Exception as e:
        print(f"[set_ingredient_alias] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to set alias: {str(e)}"}


def execute_set_purchase_source(params: dict, db_session: Session, **kwargs) -> dict:
    """Set where an ingredient should be purchased (non-Kroger source)."""
    print(f"[set_purchase_source] Called: {params.get('ingredient_name')} -> {params.get('source')}", flush=True)
    try:
        ingredient_name = params["ingredient_name"].strip()
        source = params.get("source")

        # Normalize source value
        if source:
            source = source.strip().lower()
            if source in ("null", "none", "kroger", ""):
                source = None

        # Find or create the ingredient
        ingredient = _get_or_create_ingredient(ingredient_name, db_session)
        ingredient.purchase_source = source
        ingredient.updated_at = datetime.utcnow()

        source_display = source if source else "Kroger (default)"
        print(f"[set_purchase_source] SUCCESS: '{ingredient.name}' -> {source_display}", flush=True)
        _log_event(db_session, ActionType.UPDATE_INGREDIENT, f"ingredient={ingredient_name}, source={source}", f"ingredient_id={ingredient.id}", {"ingredient_id": ingredient.id})
        return {
            "success": True,
            "ingredient_name": ingredient.name,
            "purchase_source": source,
            "message": f"'{ingredient.name}' will now be purchased from {source_display}.",
        }
    except Exception as e:
        print(f"[set_purchase_source] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to set purchase source: {str(e)}"}


def execute_get_non_kroger_items(params: dict, db_session: Session, **kwargs) -> dict:
    """Get shopping list items that need to be purchased elsewhere."""
    print("[get_non_kroger_items] Called", flush=True)
    try:
        active_list = (
            db_session.query(ShoppingList)
            .filter(ShoppingList.status == ShoppingListStatus.ACTIVE)
            .first()
        )
        if not active_list:
            return {"items": [], "by_source": {}}

        items = (
            db_session.query(ShoppingListItem)
            .join(Ingredient)
            .filter(
                ShoppingListItem.shopping_list_id == active_list.id,
                Ingredient.purchase_source.isnot(None),
            )
            .all()
        )

        # Group by source
        by_source = {}
        result_items = []
        for item in items:
            ing = item.ingredient
            source = ing.purchase_source
            if source not in by_source:
                by_source[source] = []
            item_data = {
                "name": ing.name,
                "quantity": item.quantity,
                "unit": item.unit,
                "purchase_source": source,
            }
            by_source[source].append(item_data)
            result_items.append(item_data)

        print(f"[get_non_kroger_items] SUCCESS: {len(result_items)} items across {len(by_source)} sources", flush=True)
        return {
            "items": result_items,
            "by_source": by_source,
            "total_count": len(result_items),
        }
    except Exception as e:
        print(f"[get_non_kroger_items] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to get non-Kroger items: {str(e)}"}


# =============================================================================
# Tool Dispatcher
# =============================================================================

TOOL_HANDLERS = {
    # Read
    "get_shopping_list": execute_get_shopping_list,
    "get_ingredients": execute_get_ingredients,
    "get_recipes": execute_get_recipes,
    "get_meal_plan": execute_get_meal_plan,
    "get_pantry": execute_get_pantry,
    "get_preferences": execute_get_preferences,
    "get_recipe_notes": execute_get_recipe_notes,
    "get_order_history": execute_get_order_history,
    # Write
    "add_item": execute_add_item,
    "remove_item": execute_remove_item,
    "update_item": execute_update_item,
    "clear_list": execute_clear_list,
    "finalize_order": execute_finalize_order,
    "update_ingredient": execute_update_ingredient,
    "add_recipe_note": execute_add_recipe_note,
    "add_recipe": execute_add_recipe,
    "add_meal": execute_add_meal,
    "remove_meal": execute_remove_meal,
    "generate_list_from_meals": execute_generate_list_from_meals,
    "complete_meal_plan": execute_complete_meal_plan,
    "update_preference": execute_update_preference,
    "add_pantry_item": execute_add_pantry_item,
    "add_pantry_batch": execute_add_pantry_batch,
    "update_pantry_item": execute_update_pantry_item,
    "remove_pantry_item": execute_remove_pantry_item,
    "resolve_kroger_product": execute_resolve_kroger_product,
    "confirm_kroger_product": execute_confirm_kroger_product,
    "add_to_kroger_cart": execute_add_to_kroger_cart,
    "check_off_item": execute_check_off_item,
    # Batch operations
    "import_recipes_batch": execute_import_recipes_batch,
    "match_purchases_to_ingredients": execute_match_purchases_to_ingredients,
    "update_recipe": execute_update_recipe,
    "set_ingredient_alias": execute_set_ingredient_alias,
    "set_purchase_source": execute_set_purchase_source,
    "get_non_kroger_items": execute_get_non_kroger_items,
}


def execute_tool(tool_name: str, params: dict, db_session: Session, message_id: int = None) -> dict:
    """Dispatch a tool call to its handler.

    Returns a dict with either success data or an error message.
    On exception, rolls back the session and returns an error dict.
    """
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        print(f"[execute_tool] Unknown tool: {tool_name}", flush=True)
        return {"error": f"Unknown tool: {tool_name}", "TOOL_ERROR": True}

    try:
        result = handler(params, db_session, message_id=message_id)
        return result
    except Exception as e:
        print(f"[execute_tool] EXCEPTION in {tool_name}: {type(e).__name__}: {e}", flush=True)
        try:
            db_session.rollback()
        except Exception:
            pass
        return {"error": f"{tool_name} failed: {str(e)}", "TOOL_ERROR": True}
