"""The harness against the real FakeDataSource (S2): source loading and the empty-client data dir."""

from dataclasses import replace

import pytest

from mpa.contract import BriefingRequest, assemble_pack
from mpa.data import build_data_source
from mpa.evals import scenarios
from mpa.evals.fakes import fake_deps, stream
from mpa.evals.gold import gold_briefing_text, parse_gold_briefing
from mpa.evals.models import CLIENTS, ClientKey
from mpa.evals.runner import load_sources


@pytest.mark.parametrize("client", CLIENTS)
async def test_every_gold_citation_resolves_through_the_real_data_source(client: ClientKey) -> None:
    deps = fake_deps()
    deps = replace(deps, data=build_data_source(deps.settings))
    pack = assemble_pack(stream(client, "normal"))
    sources = await load_sources(deps, pack)
    cited = {
        f"{t}:{i}" for s in parse_gold_briefing(gold_briefing_text(client)) for t, i in s.citations
    }
    assert set(sources) == cited
    assert "(source unavailable)" not in sources.values()


@pytest.mark.parametrize("client", CLIENTS)
async def test_empty_client_data_dir_loads_and_has_no_client_items(client: ClientKey) -> None:
    deps = fake_deps()
    deps = replace(deps, data=build_data_source(deps.settings))
    scenario = scenarios.build_scenario("empty_client", client)
    try:
        new_deps, _ = scenario.setup(deps, BriefingRequest(message="Prep me"))
        assert str(new_deps.settings.data_dir) != str(deps.settings.data_dir)
        name = {"halden": "Halden Pay", "brightmoor": "Brightmoor Renewables", "kettle": "Kettle"}[
            client
        ]
        assert (
            await new_deps.data.search_email(f"{name} onboarding PPA retail", limit=10) is not None
        )
        assert [e.id for e in await new_deps.data.get_calendar(query=name.split()[0])]
        with pytest.raises(KeyError):
            await new_deps.data.get_email(
                {"halden": "E47", "brightmoor": "E51", "kettle": "E35"}[client]
            )
    finally:
        scenarios.cleanup_temp_dirs()
