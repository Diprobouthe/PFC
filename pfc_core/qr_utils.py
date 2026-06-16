"""
pfc_core/qr_utils.py
--------------------
Stateless HMAC-based QR token utilities for the PFC Player QR Card system.

Scope: game_participation only.

Token design (opaque — no codename or plaintext identifier exposed):
    PFC-QR:<BASE64_PLAYER_ID>:<HMAC_HEX>

Where:
    - BASE64_PLAYER_ID  = base64url-encoded string of the player's integer ID
    - HMAC_HEX          = HMAC-SHA256 of "game_participation:<player_id>" using SECRET_KEY

The codename is NEVER included in the token or returned to the browser.
Server-side resolution: token → player_id → PlayerCodename → codename (internal only).

Security properties:
    - Opaque: scanning the QR with any reader reveals no user-identifiable information
    - Tamper-evident: HMAC prevents forging tokens for arbitrary player IDs
    - Scoped: "game_participation" scope prevents token reuse for login or other purposes
    - Stateless: no database table required for tokens
"""

import hmac
import hashlib
import base64

from django.conf import settings


_SCOPE = "game_participation"
_PREFIX = "PFC-QR"


def _compute_hmac(player_id: int) -> str:
    """Return a hex HMAC-SHA256 digest for the given player_id under the game_participation scope."""
    message = f"{_SCOPE}:{player_id}".encode("utf-8")
    key = settings.SECRET_KEY.encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def _encode_player_id(player_id: int) -> str:
    """Base64url-encode the player_id (as a decimal string) to make it opaque."""
    return base64.urlsafe_b64encode(str(player_id).encode("utf-8")).decode("ascii").rstrip("=")


def _decode_player_id(encoded: str) -> int | None:
    """Decode a base64url-encoded player_id string. Returns None on failure."""
    try:
        # Re-add padding
        padding = 4 - len(encoded) % 4
        if padding != 4:
            encoded += "=" * padding
        decoded = base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")
        return int(decoded)
    except Exception:
        return None


def generate_player_token(player_id: int) -> str:
    """
    Generate a scoped, opaque QR payload string for the given player.

    Returns a string of the form:
        PFC-QR:<BASE64_PLAYER_ID>:<HMAC_HEX>

    The codename is NOT included. The token is opaque to anyone scanning
    the QR with a generic reader.
    """
    player_id = int(player_id)
    sig = _compute_hmac(player_id)
    encoded_id = _encode_player_id(player_id)
    return f"{_PREFIX}:{encoded_id}:{sig}"


def verify_player_token(token: str) -> int | None:
    """
    Verify a QR payload string.

    Returns the player_id (int) if the token is valid, or None if invalid/tampered.
    The caller is responsible for looking up the player and their codename.
    """
    if not token or not isinstance(token, str):
        return None
    parts = token.strip().split(":")
    # Expected: ['PFC-QR', '<BASE64_PLAYER_ID>', '<HMAC_HEX>']
    if len(parts) != 3:
        return None
    prefix, encoded_id, sig = parts
    if prefix != _PREFIX:
        return None
    player_id = _decode_player_id(encoded_id)
    if player_id is None:
        return None
    expected_sig = _compute_hmac(player_id)
    # Constant-time comparison to prevent timing attacks
    if hmac.compare_digest(sig.lower(), expected_sig.lower()):
        return player_id
    return None


def generate_qr_image_data_uri(player_id: int) -> str:
    """
    Generate a QR code image for the given player and return it as a
    base64-encoded PNG data URI suitable for embedding in HTML <img> tags.

    The QR payload is fully opaque — it contains a signed reference to the
    player's ID with no codename or plaintext identifier.
    """
    import io
    import base64 as _b64
    import qrcode
    from qrcode.image.pil import PilImage

    token = generate_player_token(player_id)

    qr = qrcode.QRCode(
        version=None,  # auto-size
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(token)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white", image_factory=PilImage)

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    b64 = _b64.b64encode(buffer.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"
