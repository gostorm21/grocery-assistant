"""Claude API integration with agentic tool-use loop.

Ported from chief-of-staff agentic architecture. Replaces the single-shot
XML parsing approach with a multi-turn tool-use loop.
"""

import copy
import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic
from sqlalchemy.orm import Session

from .config import get_settings
from .models import (
    ShoppingList,
    ShoppingListStatus,
    Conversation,
    Ingredient,
    ShoppingListItem,
)
from .tools import execute_tool, get_tool_definitions

logger = logging.getLogger(__name__)

# Initialize Anthropic client
settings = get_settings()
client = Anthropic(api_key=settings.anthropic_api_key)

# Path to system prompt
SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system_prompt.txt"

# Agentic loop settings
MAX_TOOL_TURNS = settings.max_tool_turns
STATUS_CHECKPOINT_TURN = settings.status_checkpoint_turn
ENABLE_PROMPT_CACHING = settings.enable_prompt_caching


# =============================================================================
# Logging
# =============================================================================


def _log_agentic(message: str, level: str = "info"):
    """Log agentic loop messages with Railway visibility."""
    print(f"[AGENTIC] {message}", flush=True)
    if level == "debug":
        logger.debug(message)
    elif level == "warning":
        logger.warning(message)
    elif level == "error":
        logger.error(message)
    else:
        logger.info(message)


# =============================================================================
# System Prompt & Caching
# =============================================================================


def load_system_prompt() -> str:
    """Load the system prompt from file."""
    with open(SYSTEM_PROMPT_PATH, "r") as f:
        return f.read()


def _prepare_cached_system(system_text: str) -> list | str:
    """Wrap system prompt for caching if enabled."""
    if ENABLE_PROMPT_CACHING:
        return [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}]
    return system_text


def _prepare_cached_tools(tools: list) -> list:
    """Add cache_control to last tool for caching if enabled."""
    if not ENABLE_PROMPT_CACHING or not tools:
        return tools
    cached_tools = copy.deepcopy(tools)
    cached_tools[-1]["cache_control"] = {"type": "ephemeral"}
    return cached_tools


# =============================================================================
# Context Building
# =============================================================================


def get_recent_messages(db_session: Session, limit: int = 5) -> list[dict]:
    """Get recent conversation messages for context."""
    messages = (
        db_session.query(Conversation)
        .order_by(Conversation.timestamp.desc())
        .limit(limit)
        .all()
    )
    messages = list(reversed(messages))
    return [
        {
            "user": m.user,
            "message": m.message,
            "response": m.response[:800] + "..." if m.response and len(m.response) > 800 else m.response,
            "timestamp": m.timestamp.isoformat() if m.timestamp else None,
        }
        for m in messages
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
        return {"configured": False, "auth_status": "not_configured"}


def build_context(user: str, db_session: Session) -> str:
    """Build always-on context for Claude.

    Loads: shopping list (joined with Ingredient), recent messages,
    datetime, user timezone, Kroger status.

    Everything else is available on-demand via read tools.
    """
    # Shopping list items (always loaded — needed ~80% of requests)
    active_list = (
        db_session.query(ShoppingList)
        .filter(ShoppingList.status == ShoppingListStatus.ACTIVE)
        .first()
    )
    list_items = []
    if active_list:
        items = (
            db_session.query(ShoppingListItem)
            .join(Ingredient)
            .filter(ShoppingListItem.shopping_list_id == active_list.id)
            .all()
        )
        for item in items:
            parts = [f"- {item.ingredient.name}"]
            if item.quantity and item.unit:
                parts.append(f"({item.quantity} {item.unit})")
            elif item.quantity:
                parts.append(f"({item.quantity})")
            if item.ingredient.preferred_brand:
                parts.append(f"[{item.ingredient.preferred_brand}]")
            if item.added_by:
                parts.append(f"(by {item.added_by})")
            if item.ingredient.kroger_product_id:
                parts.append("[kroger: resolved]")
            if item.checked_off:
                parts.append("[checked]")
            list_items.append(" ".join(parts))

    shopping_list_str = "\n".join(list_items) if list_items else "(empty)"

    # Recent messages
    recent = get_recent_messages(db_session, limit=5)
    recent_lines = []
    for m in recent:
        recent_lines.append(f"{m['user']}: {m['message']}")
        if m.get("response"):
            recent_lines.append(f"Assistant: {m['response']}")
    recent_str = "\n".join(recent_lines) if recent_lines else "(no recent messages)"

    # Kroger status
    kroger = get_kroger_status()
    kroger_str = f"Kroger: {kroger.get('auth_status', 'not_configured')}" if kroger.get("configured") else ""

    now = datetime.now()
    timezone = settings.user_timezone

    sections = [
        f"=== CURRENT CONTEXT ===",
        f"",
        f"TODAY: {now.strftime('%Y-%m-%d %H:%M')} ({timezone})",
        f"USER: {user}",
        f"",
        f"CURRENT SHOPPING LIST ({len(list_items)} items):",
        shopping_list_str,
        f"",
        f"RECENT CONVERSATION:",
        recent_str,
    ]

    if kroger_str:
        sections.extend(["", kroger_str])

    sections.extend([
        "",
        "Use read tools (get_recipes, get_pantry, get_preferences, etc.) to load additional context on demand.",
    ])

    return "\n".join(sections)


# =============================================================================
# Response Helpers
# =============================================================================


def _extract_text_from_response(response) -> str:
    """Extract text content from Claude response."""
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    block_types = [type(b).__name__ for b in response.content]
    _log_agentic(f"No text in response, block types: {block_types}", "warning")
    return ""


# =============================================================================
# Main Agentic Loop
# =============================================================================


def get_claude_response(
    user_message: str, user: str, db_session: Session
) -> tuple[str, dict, dict]:
    """Call Claude with agentic tool-use loop.

    Args:
        user_message: The user's message text.
        user: Display name ("Erich" or "Lauren").
        db_session: Database session.

    Returns:
        Tuple of (response_text, artifacts, metadata).
    """
    system_prompt = load_system_prompt()
    context = build_context(user, db_session)
    tool_definitions = get_tool_definitions()

    full_message = f"{context}\n\n{user_message}"

    messages = [{"role": "user", "content": full_message}]

    total_input_tokens = 0
    total_output_tokens = 0
    artifacts = defaultdict(list)
    tools_called = []

    def _build_fallback_response() -> str:
        """Build a fallback response from completed tool calls."""
        if not tools_called:
            return "Done."
        parts = []
        for name in tools_called:
            parts.append(name.replace("_", " "))
        return "Completed: " + ", ".join(parts) + "."

    for turn in range(MAX_TOOL_TURNS):
        try:
            # Status checkpoint
            if turn == STATUS_CHECKPOINT_TURN:
                _log_agentic(f"Status checkpoint at turn {turn + 1}")
                messages.append({
                    "role": "user",
                    "content": f"[SYSTEM: You've used {STATUS_CHECKPOINT_TURN} tool calls. Provide a brief status update, then continue if needed.]",
                })

            _log_agentic(f"Turn {turn + 1}/{MAX_TOOL_TURNS}, messages: {len(messages)}", "debug")

            response = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=4096,
                timeout=60.0,
                system=_prepare_cached_system(system_prompt),
                tools=_prepare_cached_tools(tool_definitions),
                messages=messages,
            )

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            _log_agentic(
                f"Response: stop_reason={response.stop_reason}, "
                f"blocks={len(response.content)}",
                "debug",
            )

            # Done — no tool use
            if response.stop_reason == "end_turn":
                final_text = _extract_text_from_response(response)

                if not final_text and (artifacts or tools_called):
                    final_text = _build_fallback_response()
                    _log_agentic(f"Generated fallback response: {final_text}")

                metadata = {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "model": response.model,
                    "turns": turn + 1,
                }

                _log_agentic(
                    f"Done: {total_input_tokens} in, {total_output_tokens} out, "
                    f"{turn + 1} turns"
                )

                db_session.commit()
                return final_text, dict(artifacts), metadata

            # Process tool calls
            if response.stop_reason == "tool_use":
                assistant_content = response.content
                tool_results = []

                for block in assistant_content:
                    if block.type == "tool_use":
                        _log_agentic(f"Tool call: {block.name}", "debug")
                        try:
                            result = execute_tool(
                                block.name,
                                block.input,
                                db_session,
                            )
                            if not result.get("error") and not result.get("TOOL_ERROR"):
                                tools_called.append(block.name)
                        except Exception as tool_error:
                            _log_agentic(f"Tool {block.name} FAILED: {tool_error}", "error")
                            result = {"error": str(tool_error), "TOOL_ERROR": True}

                        # Track artifacts
                        if result.get("_artifacts"):
                            for key, val in result["_artifacts"].items():
                                artifacts[key].append(val)

                        # Clean internal keys before sending to Claude
                        clean_result = {k: v for k, v in result.items() if not k.startswith("_")}

                        # Truncate large results
                        MAX_RESULT_CHARS = 8000
                        result_str = json.dumps(clean_result)
                        if len(result_str) > MAX_RESULT_CHARS:
                            truncated_result = {
                                "truncated": True,
                                "original_size": len(result_str),
                                "success": clean_result.get("success"),
                                "recipe_id": clean_result.get("recipe_id"),
                                "item_count": clean_result.get("item_count"),
                                "kroger_product_id": clean_result.get("kroger_product_id"),
                                "ingredient_id": clean_result.get("ingredient_id"),
                                "error": clean_result.get("error"),
                            }
                            truncated_result = {k: v for k, v in truncated_result.items() if v is not None}
                            result_str = json.dumps(truncated_result)
                            _log_agentic(f"Truncated {block.name} result", "debug")

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_str,
                        })

                messages.append({"role": "assistant", "content": assistant_content})
                messages.append({"role": "user", "content": tool_results})
                continue

        except Exception as e:
            _log_agentic(f"EXCEPTION on turn {turn + 1}: {type(e).__name__}: {e}", "error")
            try:
                db_session.rollback()
            except Exception:
                pass
            if artifacts or tools_called:
                fallback_text = _build_fallback_response()
                metadata = {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "model": "claude-sonnet-4-5-20250929",
                    "turns": turn + 1,
                    "error": f"{type(e).__name__}: {e}",
                }
                return fallback_text, dict(artifacts), metadata
            raise

    # Loop limit reached
    _log_agentic(f"Loop reached {MAX_TOOL_TURNS} turns limit", "warning")

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1024,
            timeout=30.0,
            system=system_prompt,
            messages=messages + [
                {
                    "role": "user",
                    "content": "You've reached the tool call limit. Summarize what you completed and what remains.",
                }
            ],
        )

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        final_text = _extract_text_from_response(response)
        if not final_text:
            final_text = "I processed your request but ran into some complexity. Could you try rephrasing?"

        db_session.commit()

        metadata = {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "model": response.model,
            "turns": MAX_TOOL_TURNS + 1,
            "hit_limit": True,
        }

        return final_text, dict(artifacts), metadata

    except Exception as e:
        logger.exception(f"Claude API error on final turn: {e}")
        return (
            "I got stuck processing that request. Could you try rephrasing?",
            dict(artifacts),
            {"error": str(e), "turns": MAX_TOOL_TURNS},
        )
