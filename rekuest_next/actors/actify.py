import inspect
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple, Type, Union

from rekuest_next.actors.base import Passport
from rekuest_next.actors.functional import (
    FunctionalFuncActor,
    FunctionalGenActor,
    FunctionalProcessedFuncActor,
    FunctionalProcessedGenActor,
    FunctionalThreadedFuncActor,
    FunctionalThreadedGenActor,
)
from rekuest_next.actors.transport.types import ActorTransport
from rekuest_next.actors.types import ActorBuilder
from rekuest_next.agents.transport.base import AgentTransport
from rekuest_next.api.schema import (
    DefinitionInput,
    EffectInput,
    PortGroupInput,
    AssignWidgetInput,
)
from rekuest_next.definition.define import prepare_definition
from rekuest_next.structures.registry import StructureRegistry


async def async_none_provide(prov: Passport):
    """Do nothing on provide"""
    return None


async def async_none_unprovide():
    """Do nothing on unprovide"""
    return None


def higher_order_builder(builder, **params):
    """Higher order builder for actors#

    This is a higher order builder for actors. It takes a Actor class and
    returns a builder function that inserts the parameters into the class
    constructor. Akin to a partial function.
    """

    def inside_builder(**kwargs):
        return builder(
            **kwargs,
            **params,
        )

    return inside_builder


def reactify(
    function,
    structure_registry: StructureRegistry,
    bypass_shrink=False,
    bypass_expand=False,
    on_provide=None,
    on_unprovide=None,
    collections: List[str] = None,
    effects: Dict[str, EffectInput] = None,
    port_groups: Optional[List[PortGroupInput]] = None,
    groups: Optional[Dict[str, List[str]]] = None,
    is_test_for: Optional[List[str]] = None,
    widgets: Dict[str, AssignWidgetInput] = None,
    interfaces: List[str] = [],
    in_process: bool = False,
    **params,
) -> Tuple[DefinitionInput, ActorBuilder]:
    """Reactify a function

    This function takes a callable (of type async or sync function or generator) and
    returns a builder function that creates an actor that makes the function callable
    from the rekuest server.
    """

    definition = prepare_definition(
        function,
        structure_registry,
        widgets=widgets,
        interfaces=interfaces,
        port_groups=port_groups,
        collections=collections,
        groups=groups,
        effects=effects,
        is_test_for=is_test_for,
        **params,
    )

    is_coroutine = inspect.iscoroutinefunction(function)
    is_asyncgen = inspect.isasyncgenfunction(function)
    is_method = inspect.ismethod(function)

    is_generatorfunction = inspect.isgeneratorfunction(function)
    is_function = inspect.isfunction(function)

    actor_attributes = {
        "assign": function,
        "expand_inputs": not bypass_expand,
        "shrink_outputs": not bypass_shrink,
        "on_provide": on_provide if on_provide else async_none_provide,
        "on_unprovide": on_unprovide if on_unprovide else async_none_unprovide,
        "structure_registry": structure_registry,
        "definition": definition,
    }

    if is_coroutine:
        return definition, higher_order_builder(FunctionalFuncActor, **actor_attributes)
    elif is_asyncgen:
        return definition, higher_order_builder(FunctionalGenActor, **actor_attributes)
    elif is_generatorfunction and not in_process:
        return definition, higher_order_builder(
            FunctionalThreadedGenActor, **actor_attributes
        )
    elif (is_function or is_method) and not in_process:
        return definition, higher_order_builder(
            FunctionalThreadedFuncActor, **actor_attributes
        )
    elif is_generatorfunction and in_process:
        return definition, higher_order_builder(
            FunctionalProcessedGenActor, **actor_attributes
        )
    elif (is_function or is_method) and in_process:
        return definition, higher_order_builder(
            FunctionalProcessedFuncActor, **actor_attributes
        )
    else:
        raise NotImplementedError("No way of converting this to a function")