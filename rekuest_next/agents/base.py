"""Base agent class

This is the base class for all agents. It provides the basic functionality
for managing the lifecycle of the actors that are spawned from it.

"""

import asyncio
import logging
from typing import Any, Dict, Optional
import uuid

from pydantic import ConfigDict, Field

from koil import unkoil
from koil.composition import KoiledModel
from rekuest_next.actors.base import Actor
from rekuest_next.actors.types import Passport
from rekuest_next.agents.errors import AgentException, ProvisionException
from rekuest_next.agents.registry import (
    ExtensionRegistry,
    get_default_extension_registry,
)
from rekuest_next.agents.transport.base import AgentTransport, Contextual
from rekuest_next.api.schema import (
    Implementation,
    Agent,
    aensure_agent,
    ashelve,
    aunshelve,
    aset_extension_implementations,
)
from rekuest_next import messages
from rekuest_next.rath import RekuestNextRath
from .transport.errors import CorrectableConnectionFail, DefiniteConnectionFail

logger = logging.getLogger(__name__)


class BaseAgent(KoiledModel):
    """Agent

    Agents are the governing entities for every app. They are responsible for
    managing the lifecycle of the direct actors that are spawned from them through arkitekt.

    Agents are nothing else than actors in the classic distributed actor model, but they are
    always provided when the app starts and they do not provide functionality themselves but rather
    manage the lifecycle of the actors that are spawned from them.

    The actors that are spawned from them are called guardian actors and they are the ones that+
    provide the functionality of the app. These actors can then in turn spawn other actors that
    are not guardian actors. These actors are called non-guardian actors and their lifecycle is
    managed by the guardian actors that spawned them. This allows for a hierarchical structure
    of actors that can be spawned from the agents.


    """

    rath: RekuestNextRath = Field(
        description="The graph client that is used to make queries to when connecting to the rekuest server.",
    )

    name: str = Field(
        default="BaseAgent",
        description="The name of the agent. This is used to identify the agent in the system.",
    )
    instance_id: str = Field(
        default="default",
        description="The instance id of the agent. This is used to identify the agent in the system.",
    )
    shelve: Dict[str, Any] = Field(default_factory=dict)
    transport: AgentTransport
    extension_registry: ExtensionRegistry = Field(default_factory=get_default_extension_registry)
    managed_actors: Dict[str, Actor] = Field(default_factory=dict)
    interface_implementation_map: Dict[str, Implementation] = Field(default_factory=dict)
    implementation_interface_map: Dict[str, str] = Field(default_factory=dict)
    provision_passport_map: Dict[int, Passport] = Field(default_factory=dict)
    managed_assignments: Dict[str, messages.Assign] = Field(default_factory=dict)
    running_assignments: Dict[str, str] = Field(
        default_factory=dict, description="Maps assignation to actor id"
    )
    _inqueue: Contextual[asyncio.Queue] = None
    _errorfuture: Contextual[asyncio.Future] = None
    _contexts: Dict[str, Any] = None
    _states: Dict[str, Any] = None
    _agent: Contextual[Agent] = None
    started: bool = False
    running: bool = False
    model_config = ConfigDict(arbitrary_types_allowed=True)

    async def aput_on_shelve(
        self,
        identifier: str,
        value: Any,  # noqa: ANN401
    ) -> str:  # noqa: ANN401
        """Get the shelve for the agent. This is used to get the shelve
        for the agent and all the actors that are spawned from it.
        """

        if hasattr(value, "aget_label"):
            label = await value.aget_label()
        else:
            label = None

        if hasattr(value, "aget_description"):
            description = await value.aget_description()
        else:
            description = None

        key = self._agent.id + ":" + str(uuid.uuid4())
        self.shelve[key] = value
        await ashelve(
            instance_id=self.instance_id,
            identifier=identifier,
            resource_id=key,
            label=label,
            description=description,
            rath=self.rath,
        )

        return key

    async def aget_from_shelve(self, key: str) -> Any:  # noqa: ANN401
        """Get a value from the shelve. This is used to get values from the
        shelve for the agent and all the actors that are spawned from it.
        """
        assert ":" in key, "Key must be a shelve key"
        assert key.startswith(self._agent.id), "Key must be a shelve key"
        assert key in self.shelve, "Key must be a shelve key"
        return self.shelve[key]

    async def acollect(self, key: str) -> None:
        """Collect a value from the shelve. This is used to collect values from the
        shelve for the agent and all the actors that are spawned from it.
        """
        del self.shelve[key]
        await aunshelve(instance_id=self.instance_id, resource_id=key, rath=self.rath)

    async def abroadcast(self, message: messages.ToAgentMessage) -> None:
        """Broadcasts a message from a transport
        to the agent which then delegates it to agents

        This is an async funciton that puts the message on the agent
        queue. The agent will then process the message and send it to the
        actors.
        """

        await self._inqueue.put(message)

    async def on_agent_error(self, exception: Exception) -> None:
        """Called when an error occurs in the agent. This
        can be used to handle errors that occur in the agent
        """
        if self._errorfuture is None or self._errorfuture.done():
            return
        self._errorfuture.set_exception(exception)
        ...

    async def on_definite_error(self, error: DefiniteConnectionFail) -> None:
        """Async function that is called when a definite error occurs in the agent.

        This can be used to handle errors that occur in the agent
        and that are not correctable. This is used to handle errors that occur
        when the transport is not able to connect to the server anymore and
        the agent is not able to recover from it.

        Args:
            error (DefiniteConnectionFail): The error that occurred.
        """
        if self._errorfuture is None or self._errorfuture.done():
            return
        self._errorfuture.set_exception(error)
        ...

    async def on_correctable_error(self, error: CorrectableConnectionFail) -> bool:
        """Async function that is called when a correctable error occurs in the transport.
        This can be used to handle errors that occur in the transport and that
        can be corrected. An agent can decide to allow the correction of the error
        or not.
        """
        # Always correctable
        return True
        ...

    async def process(self, message: messages.ToAgentMessage) -> None:
        """Processes a message from the transport. This is used to process
        messages that are sent to the agent from the transport. The agent will
        then send the message to the actors.
        """
        logger.info(f"Agent received {message}")

        if isinstance(message, messages.Assign):
            if message.actor_id in self.managed_actors:
                actor = self.managed_actors[message.actor_id]
                self.managed_assignments[message.assignation] = message
                await actor.apass(message)
            else:
                try:
                    actor = await self.aspawn_actor_from_assign(message)

                    await actor.apass(message)

                except Exception as e:
                    await self.transport.asend(
                        messages.CriticalEvent(
                            assignation=message.assignation,
                            error=f"Not able to create actor through extensions {str(e)}",
                        )
                    )
                    raise e

        elif isinstance(
            message,
            (
                messages.Cancel,
                messages.Step,
                messages.Pause,
                messages.Resume,
            ),
        ):
            if message.assignation in self.managed_assignments:
                assignment = self.managed_assignments[message.assignation]
                actor = self.managed_actors[assignment.actor_id]
                await actor.apass(message)
            else:
                logger.warning(
                    "Received unassignation for a provision that is not running"
                    f"Managed: {self.provision_passport_map} Received: {message.provision}"
                )
                await self.transport.asend(
                    messages.CriticalEvent(
                        assignation=message.assignation,
                        error="Actors is no longer running and not managed. Probablry there was a restart",
                    )
                )

        elif isinstance(message, messages.Collect):
            for key in message.drawers:
                await self.acollect(key)

        elif isinstance(message, messages.AssignInquiry):
            if message.assignation in self.managed_assignments:
                assignment = self.managed_assignments[message.assignation]
                actor = self.managed_actors[assignment.actor_id]

                # Checking status
                status = await actor.is_assignment_still_running(assignment)
                if status:
                    await self.transport.asend(
                        messages.ProgressEvent(
                            assignation=message.assignation,
                            message="Actor is still running",
                        )
                    )
                else:
                    await self.transport.asend(
                        messages.CriticalEvent(
                            assignation=message.assignation,
                            error="The assignment was not running anymore. But the actor was still managed. This could lead to some race conditions",
                        )
                    )
            else:
                await self.transport.asend(
                    messages.CriticalEvent(
                        assignation=message.assignation,
                        error="After disconnect actor was no longer managed (probably the app was restarted)",
                    )
                )

        elif isinstance(message, messages.Collect):
            await self.shelve.adelete(message.assignation)

        else:
            raise AgentException(f"Unknown message type {type(message)}")

    async def atear_down(self) -> None:
        """Tears down the agent. This is used to tear down the agent
        and all the actors that are spawned from it.
        """

        cancelations = [actor.acancel() for actor in self.managed_actors.values()]
        # just stopping the actor, not cancelling the provision..

        for c in cancelations:
            try:
                await c
            except asyncio.CancelledError:
                pass

        if self._errorfuture is not None and not self._errorfuture.done():
            self._errorfuture.cancel()
            try:
                await self._errorfuture
            except asyncio.CancelledError:
                pass

        for extension in self.extension_registry.agent_extensions.values():
            await extension.atear_down()

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[Exception],
        exc_tb: Optional[type],
    ) -> None:
        """Exit the agent.

        This method is called when the agent is exited. It is responsible for
        tearing down the agent and all the actors that are spawned from it.

        Args:
            exc_type (Optional[type]): The type of the exception
            exc_val (Optional[Exception]): The exception value
            exc_tb (Optional[type]): The traceback

        """
        await self.atear_down()
        await self.transport.__aexit__(exc_type, exc_val, exc_tb)

    async def aregister_definitions(self, instance_id: Optional[str] = None) -> None:
        """Register all implementations that are handled by extensiosn

        This method is called by the agent when it starts and it is responsible for
        registering the tempaltes that are defined in the extensions.
        """

        self._agent = await aensure_agent(
            instance_id=instance_id,
            name=self.name,
            extensions=[
                extension.get_name()
                for extension in self.extension_registry.agent_extensions.values()
            ],
        )

        for (
            extension_name,
            extension,
        ) in self.extension_registry.agent_extensions.items():
            to_be_created_implementations = await extension.aget_implementations()

            created_implementations = await aset_extension_implementations(
                implementations=to_be_created_implementations,
                run_cleanup=extension.cleanup,
                instance_id=instance_id,
                extension=extension_name,
            )

            for implementation in created_implementations:
                self.interface_implementation_map[implementation.interface] = implementation
                self.implementation_interface_map[implementation.id] = implementation

    async def asend(self, actor: "Actor", message: messages.FromAgentMessage) -> None:
        """Sends a message to the actor. This is used for sending messages to the
        agent from the actor. The agent will then send the message to the transport.
        """
        await self.transport.asend(message)

    async def astart(self, instance_id: Optional[str] = None) -> None:
        """Starts the agent. This is used to start the agent and all the actors
        that are spawned from it. The agent will then start the transport and
        start listening for messages from the transport.
        """
        instance_id = self.instance_id

        for extension in self.extension_registry.agent_extensions.values():
            await extension.astart(instance_id)

        await self.aregister_definitions(instance_id=instance_id)

        self._errorfuture = asyncio.Future()
        await self.transport.aconnect(instance_id)

    async def aspawn_actor_from_assign(self, assign: messages.Assign) -> Actor:
        """Spawns an Actor from a Provision. This function closely mimics the
        spawining protocol within an actor. But maps implementation"""

        if assign.extension not in self.extension_registry.agent_extensions:
            raise ProvisionException(f"Extension {assign.extension} not found in agent {self.name}")
        extension = self.extension_registry.agent_extensions[assign.extension]

        actor = await extension.aspawn_actor_for_interface(self, assign.interface)

        await actor.arun()  # TODO: Maybe move this outside?
        self.managed_actors[assign.actor_id] = actor
        self.managed_assignments[assign.assignation] = assign

        return actor

    async def await_errorfuture(self) -> Exception:
        """Waits for the error future to be set. This is used to wait for"""
        return await self._errorfuture

    async def astep(self) -> None:
        """Async step that runs the agent. This is used to run the agent"""
        queue_task = asyncio.create_task(self._inqueue.get(), name="queue_future")
        error_task = asyncio.create_task(self.await_errorfuture(), name="error_future")
        done, pending = await asyncio.wait(
            [queue_task, error_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if self._errorfuture.done():
            raise self._errorfuture.exception()
        else:
            await self.process(await done.pop())

    def provide(self, instance_id: Optional[str] = None) -> None:
        """Provides the agent. This starts the agents and
        connected the transport."""
        return unkoil(self.aprovide, instance_id=instance_id)

    async def aloop(self) -> None:
        """Async loop that runs the agent. This is used to run the agent"""
        try:
            while True:
                self.running = True
                await self.astep()
        except asyncio.CancelledError:
            logger.info(f"Provisioning task cancelled. We are running {self.transport}")
            self.running = False
            raise

    async def aprovide(self, instance_id: Optional[str] = None) -> None:
        """Provides the agent.

        This starts the agents and connectes to the transport.
        It also starts the agent and starts listening for messages from the transport.

        """
        try:
            logger.info(f"Launching provisioning task. We are running {self.transport.instance_id}")
            await self.astart(instance_id=instance_id)
            logger.info("Starting to listen for requests")
            await self.aloop()
        except asyncio.CancelledError:
            logger.info("Provisioning task cancelled. We are running")
            await self.atear_down()
            raise

    async def __aenter__(self) -> None:
        """Enter the agent context manager. This is used to enter the agent

        context manager and start the agent. The agent will then start the
        transport and start listening for messages from the transport.
        """

        self._inqueue = asyncio.Queue()
        self.transport.set_callback(self)
        await self.transport.__aenter__()
        return self
