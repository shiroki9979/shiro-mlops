"""Explicit registry mapping task type names used in task definitions to their adapters."""

from collections.abc import Mapping
from types import MappingProxyType

from shiro_mlops.tasks.types.base import TaskType
from shiro_mlops.tasks.types.direct_classification import DirectClassification
from shiro_mlops.tasks.types.recursive_regression import RecursiveRegression
from shiro_mlops.tasks.types.unsupervised_reconstruction import UnsupervisedReconstruction

TASK_TYPES: Mapping[str, TaskType] = MappingProxyType(
    {
        task_type.name: task_type
        for task_type in (
            RecursiveRegression(),
            DirectClassification(),
            UnsupervisedReconstruction(),
        )
    }
)


class UnknownTaskTypeError(LookupError):
    """A task definition names a task type that is not registered."""


def get_task_type(name: str) -> TaskType:
    """Return the registered task type adapter for ``name``."""
    try:
        return TASK_TYPES[name]
    except KeyError:
        raise UnknownTaskTypeError(
            f"Unknown task type {name!r}; registered task types: {sorted(TASK_TYPES)}"
        ) from None
