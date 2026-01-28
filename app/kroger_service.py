"""Kroger API client for product search and cart management.

Handles OAuth2 authentication (client credentials for search, user auth for cart),
product search, and cart operations.
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
        # Try to refresh
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
    """Get a client credentials token for product search (no user auth needed).

    Returns:
        Access token string.

    Raises:
        Exception: If token request fails.
    """
    global _client_token, _client_token_expiry

    # Return cached token if still valid
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
    # Expire 60 seconds early to avoid edge cases
    _client_token_expiry = time.time() + token_data.get("expires_in", 1800) - 60

    logger.info("Obtained Kroger client credentials token")
    return _client_token


def _get_user_token() -> str | None:
    """Get the current user OAuth token for cart operations.

    Returns:
        Access token string, or None if not authenticated.
    """
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

    except Exception as e:
        logger.error(f"Failed to refresh Kroger user token: {e}")
        _user_token = None
        _user_token_expiry = 0


# =============================================================================
# OAuth Flow Helpers
# =============================================================================


def get_auth_url() -> str:
    """Generate the Kroger OAuth authorization URL.

    Returns:
        URL string to redirect user to for authorization.
    """
    settings = get_settings()

    params = {
        "scope": "cart.basic:write product.compact",
        "response_type": "code",
        "client_id": settings.kroger_client_id,
        "redirect_uri": settings.kroger_redirect_uri,
    }

    return f"{KROGER_AUTH_BASE}/authorize?{urlencode(params)}"


def exchange_auth_code(code: str) -> dict:
    """Exchange an authorization code for access and refresh tokens.

    Args:
        code: The authorization code from the OAuth callback.

    Returns:
        Dict with access_token, refresh_token, expires_in.

    Raises:
        Exception: If token exchange fails.
    """
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
    return token_data


# =============================================================================
# Product Search
# =============================================================================


def search_products(term: str, brand: str = None, limit: int = 5) -> list[dict]:
    """Search for products in the Kroger catalog.

    Args:
        term: Search term (e.g., "milk", "organic eggs").
        brand: Optional brand filter.
        limit: Maximum number of results.

    Returns:
        List of product dicts with: productId, description, brand, size, price.
    """
    token = _get_client_credentials_token()

    params = {
        "filter.term": term,
        "filter.limit": limit,
    }

    if brand:
        params["filter.brand"] = brand

    settings = get_settings()
    if settings.kroger_location_id:
        params["filter.locationId"] = settings.kroger_location_id

    response = requests.get(
        f"{KROGER_API_BASE}/products",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    response.raise_for_status()

    data = response.json()
    products = data.get("data", [])

    results = []
    for p in products:
        product = {
            "productId": p.get("productId", ""),
            "description": p.get("description", ""),
            "brand": p.get("brand", ""),
        }

        # Extract size from items
        items = p.get("items", [])
        if items:
            product["size"] = items[0].get("size", "")

            # Extract price
            price_info = items[0].get("price", {})
            if price_info:
                product["price"] = price_info.get("regular", price_info.get("promo"))
        else:
            product["size"] = ""
            product["price"] = None

        results.append(product)

    return results


# =============================================================================
# Cart Management
# =============================================================================


def add_items_to_cart(items: list[dict]) -> bool:
    """Add items to the user's Kroger cart.

    Args:
        items: List of dicts with "upc" and "quantity" keys.

    Returns:
        True if successful, False otherwise.
    """
    token = _get_user_token()
    if not token:
        logger.error("No user token available for cart operations")
        return False

    # Kroger cart API expects items in a specific format
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
