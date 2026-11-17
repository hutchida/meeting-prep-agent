"""The tool registry is read-only by construction."""

from __future__ import annotations

import re

from mpa.agents.tools import AGENT_TOOLS, ALLOWED_TOOL_NAMES, all_tool_names, build_registry
from mpa.loop.runner import SUBMIT, SUBMIT_FINDINGS
from test_agents_fakes import FakeData

FORBIDDEN = re.compile(
    r"send|write|delete|forward|post|update|create|remove|reply|move|put|set_", re.I
)


def test_every_tool_is_on_the_read_only_allow_list() -> None:
    names = all_tool_names(FakeData())
    assert names <= ALLOWED_TOOL_NAMES
    assert names == ALLOWED_TOOL_NAMES
    assert all(re.match(r"^(search_|get_|find_)\w+$", n) or n == SUBMIT for n in names)
    assert not [n for n in names if FORBIDDEN.search(n)]


def test_agents_get_only_their_own_tools() -> None:
    data = FakeData()
    for agent, tools in AGENT_TOOLS.items():
        assert build_registry(agent, data).names == sorted(tools)
    assert SUBMIT_FINDINGS.name == SUBMIT


def test_tool_descriptions_do_not_promise_side_effects() -> None:
    data = FakeData()
    for agent in AGENT_TOOLS:
        for spec in build_registry(agent, data).specs():
            assert not FORBIDDEN.search(spec.description.replace("Returns", "")), spec.name


async def test_handlers_validate_arguments() -> None:
    import pytest

    registry = build_registry("correspondence", FakeData())
    tool = registry.get("search_email")
    assert tool is not None
    with pytest.raises(ValueError):
        await tool.handler({"query": ""})
    with pytest.raises(ValueError):
        await tool.handler({"query": "x", "limit": "many"})
    hits = await tool.handler({"query": "Halden", "limit": 99})
    assert len(hits) <= 10
