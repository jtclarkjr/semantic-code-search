from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.asymmetric import ec
import jwt
import pytest
from fastapi import HTTPException

from app.core.auth import SupabaseJWTVerifier, decode_access_token
from app.core.config import Settings


class StaticVerifier(SupabaseJWTVerifier):
    def __init__(self, public_key):
        super().__init__(
            issuer="https://example.supabase.co/auth/v1",
            jwks_url="https://example.supabase.co/auth/v1/.well-known/jwks.json",
        )
        self._public_key = public_key

    def _get_signing_key(self, token):
        return self._public_key


def test_decode_access_token_accepts_valid_token() -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    verifier = StaticVerifier(private_key.public_key())
    token = jwt.encode(
        {
            "sub": "user-123",
            "email": "dev@example.com",
            "iss": "https://example.supabase.co/auth/v1",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        private_key,
        algorithm="ES256",
        headers={"kid": "current-key"},
    )

    claims = decode_access_token(token, verifier)

    assert claims["sub"] == "user-123"
    assert claims["email"] == "dev@example.com"


def test_decode_access_token_rejects_invalid_token() -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    verifier = StaticVerifier(private_key.public_key())

    with pytest.raises(HTTPException) as exc:
        decode_access_token("bad-token", verifier)

    assert exc.value.status_code == 401


def test_blank_audience_is_treated_as_none() -> None:
    settings = Settings(
        SCS_SUPABASE_URL="https://example.supabase.co",
        SCS_SUPABASE_PUBLISHABLE_KEY="sb_publishable_demo",
        SCS_SUPABASE_SECRET_KEY="sb_secret_demo",
        SCS_SUPABASE_JWT_AUDIENCE="",
    )

    assert settings.supabase_jwt_audience is None
