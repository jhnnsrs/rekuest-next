import asyncio
import logging
import uuid
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    Union,
    runtime_checkable,
)

from pydantic import BaseModel, Field, PrivateAttr

from koil.types import Contextual
from rekuest_next.actors.errors import ProvisionDelegateException, UnknownMessageError
from rekuest_next.actors.transport.local_transport import ProxyActorTransport
from rekuest_next.actors.transport.types import ActorTransport, AssignTransport
from rekuest_next.actors.types import Assignment, Passport, Unassignment
from rekuest_next.api.schema import (
    AssignationEventKind,
    LogLevel,
    ProvisionEventKind,
    TemplateFragment,
)
from rekuest_next.collection.collector import (
    ActorCollector,
    AssignationCollector,
    Collector,
)
from rekuest_next.definition.define import DefinitionInput
from rekuest_next.definition.registry import (
    DefinitionRegistry,
)
from rekuest_next.messages import OutMessage
from rekuest_next.structures.registry import (
    StructureRegistry,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class Agent(Protocol):
    async def abuild_actor_for_template(
        self, template: TemplateFragment, passport: Passport, transport: ActorTransport
    ) -> "Actor": ...


class Actor(BaseModel):
    passport: Passport
    transport: ActorTransport
    collector: Collector
    agent: Agent
    supervisor: Optional["Actor"] = None
    managed_actors: Dict[str, "Actor"] = Field(default_factory=dict)
    running_assignments: Dict[str, Assignment] = Field(default_factory=dict)

    _in_queue: Contextual[asyncio.Queue] = PrivateAttr(default=None)
    _running_asyncio_tasks: Dict[str, asyncio.Task] = PrivateAttr(default_factory=dict)
    _running_transports: Dict[str, AssignTransport] = PrivateAttr(default_factory=dict)
    _provision_task: asyncio.Task = PrivateAttr(default=None)
    _status: ProvisionEventKind = PrivateAttr(default=ProvisionEventKind.UNHAPPY)

    async def on_provide(self, passport: Passport):
        return None

    async def on_unprovide(self):
        return None

    async def on_assign(
        self,
        assignment: Assignment,
        collector: AssignationCollector,
        transport: AssignTransport,
    ):
        raise NotImplementedError(
            "Needs to be owerwritten in Actor Subclass. Never use this class directly"
        )

    async def aget_status(self):
        return self._status

    async def apass(self, message: Union[Unassignment, Assignment]):
        assert self._in_queue, "Actor is currently not listening"
        await self._in_queue.put(message)

    async def arun(self):
        self._in_queue = asyncio.Queue()
        self._provision_task = asyncio.create_task(self.alisten())
        return self._provision_task

    async def acancel(self):
        # Cancel Mnaged actors
        logger.info(f"Cancelling Actor {self.passport.id}")
        if self.managed_actors:
            logger.info("Cancelling Actors")
            for actor in self.managed_actors.values():
                logger.info(
                    f"Cancelling managed actor with passport {actor.passport.id}"
                )
                await actor.acancel()

        if not self._provision_task or self._provision_task.done():
            # Race condition
            return

        self._provision_task.cancel()

        try:
            await self._provision_task
        except asyncio.CancelledError:
            logger.info(f"Actor {self.passport.id} was cancelled")

    async def provide(self):
        try:
            logging.info(f"Providing {self.passport}")
            await self.on_provide(self.passport)
            await self.transport.log_event(
                kind=ProvisionEventKind.ACTIVE,
                message=f"Wonderfully provided {self.passport}",
            )

        except Exception as e:
            logging.critical(f"Providing Error {self.passport} {e}", exc_info=True)
            await self.transport.log_event(
                kind=ProvisionEventKind.DENIED,
                message=f"Providing {self.passport}",
            )

    async def unprovide(self):
        try:
            await self.on_unprovide()
            await self.transport.log_event(
                kind=ProvisionEventKind.UNHAPPY,
                message=f"Providing {self.passport}",
            )

        except Exception as e:
            logging.critical(f"Unproviding Error {self.passport} {e}", exc_info=True)
            await self.transport.log_event(
                kind=ProvisionEventKind.CRITICAL,
                message=f"Unproviding Error {self.passport} {e}",
            )

    def assign_task_done(self, task):
        logger.info(f"Assign task is done: {task}")
        if task.exception():
            try:
                raise task.exception()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(
                    f"Assign task {task} failed with exception {e}", exc_info=True
                )
            pass

    async def is_assignment_still_running(self, message: Union[Assignment]):
        if message.id in self._running_asyncio_tasks:
            return True
        return False

    async def aprocess(self, message: Union[Assignment, Unassignment]):
        logger.info(f"Actor for {self.passport}: Received {message}")

        if isinstance(message, Assignment):
            transport = self.transport.spawn(message)

            task = asyncio.create_task(
                self.on_assign(
                    message,
                    collector=self.collector,
                    transport=transport,
                )
            )

            task.add_done_callback(self.assign_task_done)

            self._running_transports[message.id] = transport
            self._running_asyncio_tasks[message.id] = task

        elif isinstance(message, Unassignment):
            if message.id in self._running_asyncio_tasks:
                task = self._running_asyncio_tasks[message.id]
                assign_transport = self._running_transports[message.id]

                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        logger.info(
                            f"Task {assign_transport.assignment} was cancelled through arkitekt. Setting Cancelled"
                        )
                        await assign_transport.log_event(
                            kind=AssignationEventKind.CANCELLED,
                            message="Cancelled remotely",
                        )
                        del self._running_asyncio_tasks[message.id]
                        del self._running_transports[message.id]

                else:
                    logger.warning(
                        f"Race Condition: Task was already done before cancellation"
                    )
                    await assign_transport.log_event(
                        kind=AssignationEventKind.ERROR,
                        message=f"Race Condition: Task was already done before cancellation",
                    )

            else:
                logger.error(
                    f"Actor for {self.passport}: Received unassignment for unknown assignation {message.id}"
                )
        else:
            raise UnknownMessageError(f"{message}")

    async def alisten(self):
        try:
            await self.provide()
            logger.info(f"Actor for {self.passport}: Is now active")

            while True:
                message = await self._in_queue.get()
                try:
                    await self.aprocess(message)
                except Exception as e:
                    logger.critical(
                        "Processing unknown message should never happen", exc_info=True
                    )

        except asyncio.CancelledError:
            logger.info("Doing Whatever needs to be done to cancel!")

            [i.cancel() for i in self._running_asyncio_tasks.values()]

            for task, assign_transport in zip(
                self._running_asyncio_tasks.values(), self._running_transports.values()
            ):
                try:
                    await task
                except asyncio.CancelledError:
                    logger.info(
                        f"Task {assign_transport.assignment} was cancelled through applicaction. Setting Critical"
                    )
                    await assign_transport.log_event(
                        kind=AssignationEventKind.CRITICAL,
                        message="Cancelled trhough application (this is not nice from the application and will be regarded as an error)",
                    )

            await self.unprovide()

        except Exception as e:
            logger.critical("Unhandled exception", exc_info=True)

            # TODO: Maybe send back an acknoledgement that we are done cancelling.
            # If we don't do this, arkitekt will not know if we failed to cancel our
            # tasks or if we succeeded. If we fail to cancel arkitekt can try to
            # kill the whole agent (maybe causing a sys.exit(1) or something)

        self._in_queue = None

    def _provision_task_done(self, task):
        logger.info(f"Provision task is done: {task}")
        if task.exception():
            raise task.exception()

    async def __aenter__(self):
        return self

    async def aspawn_actor(
        self,
        template: TemplateFragment,
        on_log_event: Callable[[OutMessage], Awaitable[None]],
    ) -> "SerializingActor":
        """Spawns an Actor managed by thisfrom the definition of the given interface"""

        passport = Passport(
            provision=self.passport.provision,
            parent=self.passport.id,
            instance_id=self.passport.instance_id,
        )

        transport = ProxyActorTransport(passport=passport, on_log_event=on_log_event)

        actor = await self.agent.abuild_actor_for_template(
            template,
            passport,
            transport,
        )

        self.managed_actors[actor.passport.id] = actor
        return actor

    async def __aexit__(self, exc_type, exc, tb):
        if self._provision_task and not self._provision_task.done():
            await self.acancel()

    class Config:
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True
        copy_on_model_validation = "none"


class SerializingActor(Actor):
    definition: DefinitionInput
    structure_registry: StructureRegistry
    expand_inputs: bool = True
    shrink_outputs: bool = True


Actor.update_forward_refs()
SerializingActor.update_forward_refs()