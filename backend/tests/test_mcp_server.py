import asyncio

import pytest

pytest.importorskip("mcp")

from app.ai import tools
from app.mcp_server import build_server


def test_server_exposes_exactly_the_copilot_tools():
    listed = asyncio.run(build_server().list_tools())
    assert {t.name for t in listed} == set(tools.TOOLS)


def test_tool_descriptions_match_the_copilot_specs():
    listed = {t.name: t.description for t in asyncio.run(build_server().list_tools())}
    for name, spec in tools.SPECS.items():
        assert listed[name] == spec["function"]["description"]


def test_get_meter_requires_a_meter_id():
    listed = {t.name: t for t in asyncio.run(build_server().list_tools())}
    assert "meter_id" in listed["get_meter"].inputSchema["required"]
