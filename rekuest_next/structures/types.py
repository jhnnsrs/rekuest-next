from typing import Protocol, Optional
from rekuest_next.api.schema import (
    AssignWidgetInput,
    ReturnWidgetInput,
    PortInput,
    PortScope,
)
from pydantic import BaseModel
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Optional,
    Type,
    TypeVar,
    Protocol,
    runtime_checkable,
)


class PortBuilder(Protocol):
    def __call__(
        self,
        cls: type,
        assign_widget: Optional[AssignWidgetInput],
        return_widget: Optional[ReturnWidgetInput],
    ) -> PortInput: ...


class FullFilledStructure(BaseModel):
    fullfilled_by: str
    cls: Type
    identifier: str
    scope: PortScope
    aexpand: Callable[
        [
            str,
        ],
        Awaitable[Any],
    ]
    ashrink: Callable[
        [
            any,
        ],
        Awaitable[str],
    ]
    acollect: Callable[
        [
            str,
        ],
        Awaitable[Any],
    ]
    predicate: Callable[[Any], bool]
    convert_default: Callable[[Any], str]
    default_widget: Optional[AssignWidgetInput]
    default_returnwidget: Optional[ReturnWidgetInput]

    class Config:
        arbitrary_types_allowed = True
        copy_on_model_validation = False
        extra = "forbid"


class FullFilledArg(BaseModel):
    key: str
    default: Optional[Any]
    cls: Any
