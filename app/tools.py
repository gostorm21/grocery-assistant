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
        "description": "Confirm a Kroger product match for an ingredient. Stores the kroger_product_id, brand, and size on the Ingredient record permanently.",
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
]


def get_tool_definitions() -> list:
    """Return tool definitions for Claude API."""
    return TOOL_DEFINITIONS


# =============================================================================
# Helpers
# =============================================================================


def _get_or_create_ingredient(name: str, db_session: Session) -> Ingredient:
    """Find existing ingredient by normalized name, or create new one."""
    normalized = normalize_ingredient_name(name)
    ingredient = (
        db_session.query(Ingredient)
        .filter(Ingredient.normalized_name == normalized)
        .first()
    )
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
    """Get all pantry items."""
    print("[get_pantry] Called", flush=True)
    items = db_session.query(PantryItem).order_by(PantryItem.item_name).all()
    result = [
        {
            "item_name": i.item_name,
            "quantity": i.quantity,
            "unit": i.unit,
        }
        for i in items
    ]
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
        return {
            "success": True,
            "item_id": item.id,
            "ingredient_id": ingredient.id,
            "name": ingredient.name,
            "preferred_brand": ingredient.preferred_brand,
            "kroger_product_id": ingredient.kroger_product_id,
            "has_kroger_mapping": ingredient.kroger_product_id is not None,
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
        return {"success": True, "removed": removed_name}
    except Exception as e:
        print(f"[remove_item] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to remove item: {str(e)}"}


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

        print(f"[add_recipe] SUCCESS: recipe id={recipe.id}, {len(new_ingredients)} ingredients, {len(unmapped)} unmapped", flush=True)
        return {
            "success": True,
            "recipe_id": recipe.id,
            "name": name,
            "ingredient_count": len(new_ingredients),
            "ingredients": new_ingredients,
            "unmapped_ingredients": [i["name"] for i in unmapped],
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
        return {"success": True, "user": user, "category": category, "value": value}
    except Exception as e:
        print(f"[update_preference] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to update preference: {str(e)}"}


def execute_add_pantry_item(params: dict, db_session: Session, **kwargs) -> dict:
    """Add or upsert a pantry item."""
    print(f"[add_pantry_item] Called: {params.get('item_name')}", flush=True)
    try:
        item_name = params["item_name"].strip()

        # Also ensure ingredient record exists
        _get_or_create_ingredient(item_name, db_session)

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
            existing.updated_at = datetime.utcnow()
            print(f"[add_pantry_item] SUCCESS: updated '{item_name}'", flush=True)
            return {"success": True, "item_name": item_name, "action": "updated"}
        else:
            new_item = PantryItem(item_name=item_name, quantity=quantity, unit=unit)
            db_session.add(new_item)
            print(f"[add_pantry_item] SUCCESS: added '{item_name}'", flush=True)
            return {"success": True, "item_name": item_name, "action": "added"}
    except Exception as e:
        print(f"[add_pantry_item] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to add pantry item: {str(e)}"}


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

        results = search_products(ingredient_name, brand=brand_hint, limit=5)
        print(f"[resolve_kroger_product] SUCCESS: {len(results)} results for '{ingredient_name}'", flush=True)
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

        ingredient = _get_or_create_ingredient(ingredient_name, db_session)
        ingredient.kroger_product_id = kroger_product_id
        if brand:
            ingredient.preferred_brand = brand
        if size:
            ingredient.preferred_size = size
        ingredient.updated_at = datetime.utcnow()

        print(f"[confirm_kroger_product] SUCCESS: '{ingredient.name}' -> {kroger_product_id}", flush=True)
        return {
            "success": True,
            "ingredient_id": ingredient.id,
            "name": ingredient.name,
            "kroger_product_id": kroger_product_id,
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
        for item in items:
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
            print(f"[add_to_kroger_cart] SUCCESS: {len(resolved)} items", flush=True)
            return {"success": True, "items_added": len(resolved)}
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
        return {"success": True, "name": item.ingredient.name, "checked_off": item.checked_off}
    except Exception as e:
        print(f"[check_off_item] FAILED: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Failed to check off item: {str(e)}"}


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
    "update_pantry_item": execute_update_pantry_item,
    "remove_pantry_item": execute_remove_pantry_item,
    "resolve_kroger_product": execute_resolve_kroger_product,
    "confirm_kroger_product": execute_confirm_kroger_product,
    "add_to_kroger_cart": execute_add_to_kroger_cart,
    "check_off_item": execute_check_off_item,
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
