"""Kroger API client for product search and cart management.

Handles OAuth2 authentication (client credentials for search, user auth for cart),
product search, and cart operations. Tokens are persisted to database to survive restarts.
"""

import logging
import time
from urllib.parse import urlencode

import requests

from .config import get_settings

logger = logging.getLogger(__name__)

# Kroger API base URLs
KROGER_API_BASE = "https://api.kroger.com/v1"
KROGER_AUTH_BASE = "https://api.kroger.com/v1/connect/oauth2"

# Token cache
_client_token: str | None = None
_client_token_expiry: float = 0
_user_token: str | None = None
_user_refresh_token: str | None = None
_user_token_expiry: float = 0


# =============================================================================
# Database Token Persistence
# =============================================================================


def _load_tokens_from_db() -> None:
    """Load user tokens from database on startup."""
    global _user_token, _user_refresh_token, _user_token_expiry

    try:
        from .database import get_db_session
        from .models import KrogerToken

        with get_db_session() as db_session:
            token_row = db_session.query(KrogerToken).first()
            if token_row and token_row.refresh_token:
                _user_token = token_row.access_token
                _user_refresh_token = token_row.refresh_token
                _user_token_expiry = token_row.token_expiry or 0
                print(f"[KROGER] Loaded tokens from database (expiry={_user_token_expiry})", flush=True)
            else:
                print("[KROGER] No saved tokens in database", flush=True)
    except Exception as e:
        print(f"[KROGER] Failed to load tokens from DB: {e}", flush=True)


def _save_tokens_to_db() -> None:
    """Save current user tokens to database."""
    try:
        from .database import get_db_session
        from .models import KrogerToken

        with get_db_session() as db_session:
            token_row = db_session.query(KrogerToken).first()
            if not token_row:
                token_row = KrogerToken()
                db_session.add(token_row)

            token_row.access_token = _user_token
            token_row.refresh_token = _user_refresh_token
            token_row.token_expiry = _user_token_expiry
            db_session.commit()
            print("[KROGER] Saved tokens to database", flush=True)
    except Exception as e:
        print(f"[KROGER] Failed to save tokens to DB: {e}", flush=True)


# Load tokens from DB on module import (after tables exist)
try:
    _load_tokens_from_db()
except Exception:
    pass  # Tables may not exist yet during migration


# =============================================================================
# Configuration & Status
# =============================================================================


def is_configured() -> bool:
    """Check if Kroger API credentials are configured."""
    try:
        settings = get_settings()
        return bool(settings.kroger_client_id and settings.kroger_client_secret)
    except Exception:
        return False


def get_auth_status() -> str:
    """Get current authentication status.

    Returns:
        "connected" | "not_connected" | "not_configured"
    """
    if not is_configured():
        return "not_configured"
    if is_user_authenticated():
        return "connected"
    return "not_connected"


def is_user_authenticated() -> bool:
    """Check if a user OAuth token is available and valid."""
    global _user_token, _user_token_expiry
    if not _user_token:
        return False
    if time.time() >= _user_token_expiry:
        try:
            _refresh_user_token()
            return _user_token is not None
        except Exception:
            return False
    return True


# =============================================================================
# Token Management
# =============================================================================


def _get_client_credentials_token() -> str:
    """Get a client credentials token for product search (no user auth needed)."""
    global _client_token, _client_token_expiry

    if _client_token and time.time() < _client_token_expiry:
        return _client_token

    settings = get_settings()

    response = requests.post(
        f"{KROGER_AUTH_BASE}/token",
        data={
            "grant_type": "client_credentials",
            "scope": "product.compact",
        },
        auth=(settings.kroger_client_id, settings.kroger_client_secret),
        timeout=10,
    )
    response.raise_for_status()

    token_data = response.json()
    _client_token = token_data["access_token"]
    _client_token_expiry = time.time() + token_data.get("expires_in", 1800) - 60

    logger.info("Obtained Kroger client credentials token")
    return _client_token


def _get_user_token() -> str | None:
    """Get the current user OAuth token for cart operations."""
    global _user_token, _user_token_expiry

    if not _user_token:
        return None

    if time.time() >= _user_token_expiry:
        _refresh_user_token()

    return _user_token


def _refresh_user_token() -> None:
    """Refresh the user OAuth token using the refresh token."""
    global _user_token, _user_refresh_token, _user_token_expiry

    if not _user_refresh_token:
        _user_token = None
        return

    settings = get_settings()

    try:
        response = requests.post(
            f"{KROGER_AUTH_BASE}/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": _user_refresh_token,
            },
            auth=(settings.kroger_client_id, settings.kroger_client_secret),
            timeout=10,
        )
        response.raise_for_status()

        token_data = response.json()
        _user_token = token_data["access_token"]
        _user_refresh_token = token_data.get("refresh_token", _user_refresh_token)
        _user_token_expiry = time.time() + token_data.get("expires_in", 1800) - 60

        logger.info("Refreshed Kroger user token")
        _save_tokens_to_db()

    except Exception as e:
        logger.error(f"Failed to refresh Kroger user token: {e}")
        _user_token = None
        _user_token_expiry = 0


# =============================================================================
# OAuth Flow Helpers
# =============================================================================


def get_auth_url() -> str:
    """Generate the Kroger OAuth authorization URL."""
    settings = get_settings()

    params = {
        "scope": "cart.basic:write product.compact profile.compact",
        "response_type": "code",
        "client_id": settings.kroger_client_id,
        "redirect_uri": settings.kroger_redirect_uri,
    }

    return f"{KROGER_AUTH_BASE}/authorize?{urlencode(params)}"


def exchange_auth_code(code: str) -> dict:
    """Exchange an authorization code for access and refresh tokens."""
    global _user_token, _user_refresh_token, _user_token_expiry

    settings = get_settings()

    response = requests.post(
        f"{KROGER_AUTH_BASE}/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.kroger_redirect_uri,
        },
        auth=(settings.kroger_client_id, settings.kroger_client_secret),
        timeout=10,
    )
    response.raise_for_status()

    token_data = response.json()
    _user_token = token_data["access_token"]
    _user_refresh_token = token_data.get("refresh_token")
    _user_token_expiry = time.time() + token_data.get("expires_in", 1800) - 60

    logger.info("Exchanged Kroger auth code for user tokens")
    _save_tokens_to_db()
    return token_data


# =============================================================================
# Product Search
# =============================================================================


def _simplify_search_term(term: str) -> str:
    """Simplify search term by removing common prefixes that may interfere with search.

    Strips words like 'organic', 'fresh', 'frozen' that may limit results.
    """
    prefixes_to_strip = [
        "organic",
        "fresh",
        "frozen",
        "dried",
        "canned",
        "whole",
        "raw",
        "natural",
        "pure",
    ]

    words = term.lower().split()
    filtered = [w for w in words if w not in prefixes_to_strip]

    # Return original if all words were stripped
    if not filtered:
        return term

    return " ".join(filtered)


def _do_search(
    term: str,
    brand: str = None,
    location_id: str = None,
    limit: int = 20,
) -> list[dict]:
    """Execute a single Kroger product search with given parameters.

    Note: brand parameter is ignored - Kroger's brand filter is case-sensitive
    and too fragile. We include brand in the search term instead.
    """
    token = _get_client_credentials_token()

    # If brand hint provided, prepend to search term instead of using filter
    # This is more forgiving than the case-sensitive brand filter
    search_term = f"{brand} {term}" if brand else term

    params = {
        "filter.term": search_term,
        "filter.limit": limit,
    }

    # Don't use filter.brand - it's case-sensitive and causes 0 results
    # when casing doesn't match exactly (e.g., "boar's head" vs "Boar's Head")

    if location_id:
        params["filter.locationId"] = location_id

    url = f"{KROGER_API_BASE}/products"

    # Enhanced debug logging
    print(f"[KROGER SEARCH] === NEW SEARCH ===", flush=True)
    print(f"[KROGER SEARCH] Term: '{search_term}'", flush=True)
    print(f"[KROGER SEARCH] Location: {location_id}", flush=True)
    print(f"[KROGER SEARCH] Full URL: {url}?{urlencode(params)}", flush=True)

    response = requests.get(
        url,
        params=params,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )

    print(f"[KROGER SEARCH] Status: {response.status_code}", flush=True)

    response.raise_for_status()

    data = response.json()
    products = data.get("data", [])

    # Log what we got back
    print(f"[KROGER SEARCH] Results count: {len(products)}", flush=True)
    if products:
        # Show first result's category to debug category issues
        first = products[0]
        print(f"[KROGER SEARCH] First result: {first.get('description')}", flush=True)
        print(f"[KROGER SEARCH] Categories: {first.get('categories', [])}", flush=True)
        print(f"[KROGER SEARCH] Brand: {first.get('brand')}", flush=True)
    else:
        # Log full response when empty to see if there's an error message
        print(f"[KROGER SEARCH] Empty response body: {response.text[:1000]}", flush=True)

    results = []
    for p in products:
        product = {
            "productId": p.get("productId", ""),
            "description": p.get("description", ""),
            "brand": p.get("brand", ""),
        }

        items = p.get("items", [])
        if items:
            item = items[0]
            product["size"] = item.get("size", "")
            price_info = item.get("price", {})
            if price_info:
                product["price"] = price_info.get("regular", price_info.get("promo"))
            # Add fulfillment/availability info
            fulfillment = item.get("fulfillment", {})
            product["in_store"] = fulfillment.get("inStore", False)
            product["curbside"] = fulfillment.get("curbside", False)
            product["delivery"] = fulfillment.get("delivery", False)
        else:
            product["size"] = ""
            product["price"] = None
            product["in_store"] = False
            product["curbside"] = False
            product["delivery"] = False

        results.append(product)

    return results


def search_products(term: str, brand: str = None, limit: int = 20) -> dict:
    """Search for products in the Kroger catalog.

    Uses a fallback strategy:
    1. Search with location filter
    2. If no results, retry without location filter
    3. If still no results, simplify the search term and retry

    Returns dict with:
        - results: list of products
        - location_filtered: whether results are filtered to user's store
        - location_id: the location ID used (if any)
    """
    settings = get_settings()
    location_id = settings.kroger_location_id if settings.kroger_location_id else None

    # Try with location first (if configured)
    if location_id:
        results = _do_search(term, brand=brand, location_id=location_id, limit=limit)
        if results:
            print(f"[KROGER SEARCH] Found {len(results)} results with location filter", flush=True)
            return {"results": results, "location_filtered": True, "location_id": location_id}
        print("[KROGER SEARCH] No results with location filter, retrying without...", flush=True)

    # Fallback: no location filter
    results = _do_search(term, brand=brand, location_id=None, limit=limit)
    if results:
        print(f"[KROGER SEARCH] Found {len(results)} results without location filter", flush=True)
        return {"results": results, "location_filtered": False, "location_id": location_id}

    # Fallback: simplified term
    simple_term = _simplify_search_term(term)
    if simple_term != term.lower():
        print(f"[KROGER SEARCH] Retrying with simplified term: '{simple_term}'", flush=True)
        results = _do_search(simple_term, brand=brand, location_id=None, limit=limit)
        if results:
            print(f"[KROGER SEARCH] Found {len(results)} results with simplified term", flush=True)
            return {"results": results, "location_filtered": False, "location_id": location_id}

    print(f"[KROGER SEARCH] No results found for '{term}' after all fallbacks", flush=True)
    return {"results": [], "location_filtered": False, "location_id": location_id}


# =============================================================================
# Cart Management
# =============================================================================


def add_items_to_cart(items: list[dict]) -> bool:
    """Add items to the user's Kroger cart."""
    token = _get_user_token()
    if not token:
        logger.error("No user token available for cart operations")
        return False

    cart_items = [
        {"upc": item["upc"], "quantity": item.get("quantity", 1)}
        for item in items
    ]

    try:
        response = requests.put(
            f"{KROGER_API_BASE}/cart/add",
            json={"items": cart_items},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        response.raise_for_status()

        logger.info(f"Added {len(cart_items)} items to Kroger cart")
        return True

    except requests.exceptions.HTTPError as e:
        logger.error(f"Kroger cart API error: {e}")
        if e.response is not None:
            logger.error(f"Response body: {e.response.text}")
        return False

    except Exception as e:
        logger.error(f"Kroger cart error: {e}")
        return False


# =============================================================================
# Purchase History
# =============================================================================


def get_purchase_history(limit: int = 50) -> list[dict]:
    """Get user's recent purchase history from Kroger.

    Returns list of recently purchased products with brand/size info.
    Requires profile.compact scope and user authentication.
    """
    token = _get_user_token()
    if not token:
        logger.error("No user token available for purchase history")
        return []

    try:
        response = requests.get(
            f"{KROGER_API_BASE}/me/purchases",
            params={"filter.limit": limit},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        response.raise_for_status()

        data = response.json()
        purchases = data.get("data", [])

        results = []
        for p in purchases:
            product = {
                "productId": p.get("productId", ""),
                "upc": p.get("upc", ""),
                "description": p.get("description", ""),
                "brand": p.get("brand", ""),
                "category": p.get("categories", [""])[0] if p.get("categories") else "",
                "size": p.get("size", ""),
                "purchaseCount": p.get("quantity", 1),
            }
            results.append(product)

        logger.info(f"Retrieved {len(results)} items from purchase history")
        return results

    except requests.exceptions.HTTPError as e:
        logger.error(f"Kroger purchase history API error: {e}")
        if e.response is not None:
            logger.error(f"Response body: {e.response.text}")
        return []

    except Exception as e:
        logger.error(f"Kroger purchase history error: {e}")
        return []
