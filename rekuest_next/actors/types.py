from typing import Protocol, runtime_checkable, Callable, Awaitable, Any
from rekuest_next.structures.registry import StructureRegistry
from rekuest_next.api.schema import PortGroupInput, AssignationEventKind
from rekuest_next.definition.define import DefinitionInput
from typing import Optional, List, Dict, Tuple, Any
from pydantic import BaseModel, Field
import uuid



class Passport(BaseModel):
    instance_id: str
    provision: str
    parent: Optional[str]
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class Assignment(BaseModel):
    assignation: Optional[str]
    parent: Optional[str]
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    args: Dict[str, Any] = Field(default_factory=dict)
    user: Optional[str]
    reference: Optional[str]
    context: Dict[str, Any]  = Field(default_factory=dict)


class AssignmentUpdate(BaseModel):
    assignment: str
    status: AssignationEventKind
    message: Optional[str]
    parent: Optional[str]
    progress: Optional[int]
    returns: Optional[List[Any]]


class Unassignment(BaseModel):
    assignation: str
    id: str
    context: Dict[str, Any]  = Field(default_factory=dict)

@runtime_checkable
class ActorBuilder(Protocol):
    def __call__(
        self,
        passport: Passport,
        transport: Any,
        collector: Any,
        definition_registry: Any,
    ) -> Any: ...


@runtime_checkable
class Actifier(Protocol):
    """An actifier is a function that takes a callable and a structure registry
    as well as optional arguments

    """

    def __call__(
        self,
        function: Callable,
        structure_registry: StructureRegistry,
        port_groups: Optional[List[PortGroupInput]] = None,
        groups: Optional[Dict[str, List[str]]] = None,
        is_test_for: Optional[List[str]] = None,
        **kwargs,
    ) -> Tuple[DefinitionInput, ActorBuilder]: ...


@runtime_checkable
class OnProvide(Protocol):
    """An on_provide is a function that takes a provision and a transport and returns
    an awaitable

    """

    def __call__(
        self,
        passport: Passport,
    ) -> Awaitable[Any]: ...


@runtime_checkable
class OnUnprovide(Protocol):
    """An on_provide is a function that takes a provision and a transport and returns
    an awaitable

    """

    def __call__(self) -> Awaitable[Any]: ...
