from __future__ import annotations

from typing import Any, Dict


class AuthService:
    def __init__(self, public_client: Any) -> None:
        self.public_client = public_client

    def login(self, email: str, password: str) -> Dict[str, Any]:
        result = self.public_client.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
        session = getattr(result, "session", None)
        user = getattr(result, "user", None)
        if session is None or not getattr(session, "access_token", None):
            raise ValueError("Supabase did not return an access token.")
        return {
            "access_token": session.access_token,
            "refresh_token": getattr(session, "refresh_token", None),
            "expires_at": getattr(session, "expires_at", None),
            "token_type": "bearer",
            "user": {
                "id": getattr(user, "id", None),
                "email": getattr(user, "email", None),
            },
        }
