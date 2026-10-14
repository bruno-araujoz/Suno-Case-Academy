"""Live self-healing demo against the real sites (network). Run: uv run pytest -m live."""

import pytest

from scraper.core.config import get_settings
from scraper.heal.demo import run_demo

pytestmark = pytest.mark.live


@pytest.mark.parametrize("scenario", ["404", "stale", "html"])
async def test_heal_demo_scenario_repairs_live(scenario, capsys):
    assert await run_demo(get_settings(), [scenario]) == 0
    out = capsys.readouterr().out
    assert "status=healed" in out, out
