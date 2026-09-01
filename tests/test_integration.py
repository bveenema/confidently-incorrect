import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="no live API clients yet")
def test_integration_placeholder() -> None:
    pass
