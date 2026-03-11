from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import jwt
from jwt import PyJWKClient, PyJWKClientError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class UserContext:
    user_id: str
    email: Optional[str]
    role: str
    access_token: str
    claims: Dict[str, Any]


class SupabaseJWTVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: Optional[str] = None,
        jwks_url: str,
        jwks_cache_ttl_seconds: int = 300,
        jwks_client: Optional[PyJWKClient] = None,
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.audience = audience.strip() if isinstance(audience, str) and audience.strip() else None
        self.jwks_url = jwks_url
        self.jwks_client = jwks_client or PyJWKClient(
            jwks_url,
            cache_jwk_set=True,
            lifespan=jwks_cache_ttl_seconds,
        )

    def decode(self, token: str) -> Dict[str, Any]:
        try:
            signing_key = self._get_signing_key(token)
            return jwt.decode(
                token,
                signing_key,
                algorithms=["ES256"],
                issuer=self.issuer,
                audience=self.audience,
                options={
                    "verify_aud": bool(self.audience),
                    "require": ["exp", "iss", "sub"],
                },
            )
        except (jwt.PyJWTError, PyJWKClientError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid bearer token.",
            ) from exc

    def _get_signing_key(self, token: str) -> Any:
        return self.jwks_client.get_signing_key_from_jwt(token).key


def decode_access_token(token: str, token_verifier: SupabaseJWTVerifier) -> Dict[str, Any]:
    return token_verifier.decode(token)


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> UserContext:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    container = request.app.state.container
    claims = decode_access_token(credentials.credentials, container.token_verifier)
    subject = claims.get("sub")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing a subject.",
        )
    return UserContext(
        user_id=str(subject),
        email=claims.get("email"),
        role=str(claims.get("role", "authenticated")),
        access_token=credentials.credentials,
        claims=claims,
    )
