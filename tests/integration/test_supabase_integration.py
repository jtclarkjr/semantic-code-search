import os

import pytest


pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_SUPABASE_INTEGRATION"),
    reason="Set RUN_SUPABASE_INTEGRATION=1 and provide real Supabase credentials to run integration tests.",
)


def test_supabase_integration_placeholder() -> None:
    assert os.getenv("SCS_SUPABASE_URL")
    assert os.getenv("SCS_SUPABASE_PUBLISHABLE_KEY")
    assert os.getenv("SCS_SUPABASE_SECRET_KEY")
