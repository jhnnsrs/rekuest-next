from fieldz import fields   
from rekuest_next.structures.model import model
from typing import Type, TypeVar, Callable
from typing import Dict, Any
import inspect 


T = TypeVar("T")

def is_context(cls: Type[T]) -> bool:
    return getattr(cls, "__rekuest_context__", False)

def get_context_name(cls: Type[T]) -> str:
    x =  getattr(cls, "__rekuest_context__", None)
    if x is None:
        raise ValueError(f"Class {cls} is not a context")
    return x

def context(name: str) -> Callable[[Type[T]], Type[T]]:

    def wrapper(cls: Type[T]) -> Type[T]:

        setattr(cls, "__rekuest_context__", name)
        return  cls
    

    return wrapper




def prepare_context_variables(function) -> Dict[str, Any]:

    sig = inspect.signature(function)
    parameters = sig.parameters

    state_variables = {}
    state_returns = {}


    for key, value in parameters.items():
        if is_context(value):
            state_variables[key] = value.__rekuest_state__


    returns = sig.return_annotation

    if hasattr(returns, "_name"):
        if returns._name == "Tuple":
            for index, cls in enumerate(returns.__args__):
                if is_context(cls):
                    state_returns[index] = cls.__rekuest_state__
        else:
            if is_context(returns):
                state_returns[0] = returns.__rekuest_state__


    return state_variables, state_returns


