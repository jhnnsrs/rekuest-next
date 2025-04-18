from rekuest_next.api.schema import PortInput, PortKind, ChildPortInput, PortScope
from pydantic import ValidationError
import pytest


def test_argport_input_errors():
    with pytest.raises(ValidationError):
        # kind is required and only accepts PortKind
        PortInput(kind="lala")

    with pytest.raises(ValidationError):
        # key and nullable are required
        PortInput(kind=PortKind.BOOL)

    with pytest.raises(ValidationError):
        # nullable is required
        PortInput(kind=PortKind.BOOL, key="search")

    with pytest.raises(ValidationError):
        # identifier is required for STRUCTURE
        PortInput(kind=PortKind.STRUCTURE, key="search", nullable=False)

    with pytest.raises(ValidationError):
        # child is required for List
        PortInput(kind=PortKind.LIST, key="search", nullable=False)


def test_argport():
    PortInput(kind=PortKind.BOOL, key="search", nullable=False, scope=PortScope.GLOBAL)
    PortInput(kind=PortKind.STRING, key="search", nullable=False, scope=PortScope.GLOBAL)

    PortInput(
        kind=PortKind.STRUCTURE,
        identifier="hm/karl",
        key="search",
        nullable=False,
        scope=PortScope.GLOBAL,
    )

    PortInput(
        kind=PortKind.LIST,
        children=[ChildPortInput(key="0", kind=PortKind.BOOL, nullable=False, scope=PortScope.GLOBAL)],
        scope=PortScope.GLOBAL,
        nullable=False,
        key="search",
    )
