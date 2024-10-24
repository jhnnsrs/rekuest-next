from rekuest_next.postmans.utils import actoruse
from rekuest_next.definition.define import prepare_definition
import asyncio
import pytest
from rekuest_next.definition.registry import DefinitionRegistry
from rekuest_next.agents.base import BaseAgent
from rekuest_next.agents.transport.mock import MockAgentTransport


@pytest.mark.skip
@pytest.mark.asyncio
async def test_local_use(simple_registry):
    # THe function we would like to run

    d = DefinitionRegistry()

    def func(hallo: int) -> int:
        """This function

        This function is a test function

        """

        return 1

    # Tasks that are normally done by arkitket
    d.register(func, simple_registry)

    agenttransport = MockAgentTransport()
    agent = BaseAgent(transport=agenttransport)

    async def do_func():
        async with actoruse(interface=func, structure_registry=simple_registry) as a:
            return await a.aassign(4)

    async with agent:
        result = await do_func

    assert result == 1, "The result should be 1"
