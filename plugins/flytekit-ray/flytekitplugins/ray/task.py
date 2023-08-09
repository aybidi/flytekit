import base64
import json
import typing
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import ray
from flytekitplugins.ray.models import HeadGroupSpec, RayCluster, RayJob, WorkerGroupSpec
from google.protobuf.json_format import MessageToDict

from flytekit.configuration import SerializationSettings
from flytekit.core.context_manager import ExecutionParameters
from flytekit.core.python_function_task import PythonFunctionTask
from flytekit.extend import TaskPlugins


@dataclass
class HeadNodeConfig:
    ray_start_params: typing.Optional[typing.Dict[str, str]] = None
    resources: typing.Optional[typing.Dict[str, str]] = None


@dataclass
class WorkerNodeConfig:
    group_name: str
    replicas: int
    min_replicas: typing.Optional[int] = None
    max_replicas: typing.Optional[int] = None
    ray_start_params: typing.Optional[typing.Dict[str, str]] = None
    resources: typing.Optional[typing.Dict[str, str]] = None


@dataclass
class RayJobConfig:
    worker_node_config: typing.List[WorkerNodeConfig]
    head_node_config: typing.Optional[HeadNodeConfig] = None
    runtime_env: typing.Optional[dict] = None
    address: typing.Optional[str] = None
    # TODO: This config should be added to flyteidl. https://github.com/flyteorg/flyteidl/blob/95e11cca2dac18b727f122bbc4456ea6ab499289/protos/flyteidl/plugins/ray.proto#L8
    config_override: typing.Optional[typing.Dict[str, str]] = None
    namespace: typing.Optional[str] = None
    k8s_sa: typing.Optiona[str] = None


class RayFunctionTask(PythonFunctionTask):
    """
    Actual Plugin that transforms the local python code for execution within Ray job.
    """

    _RAY_TASK_TYPE = "ray"

    def __init__(self, task_config: RayJobConfig, task_function: Callable, **kwargs):
        super().__init__(task_config=task_config, task_type=self._RAY_TASK_TYPE, task_function=task_function, **kwargs)
        self._task_config = task_config

    def pre_execute(self, user_params: ExecutionParameters) -> ExecutionParameters:
        ray.init(address=self._task_config.address)
        return user_params

    def post_execute(self, user_params: ExecutionParameters, rval: Any) -> Any:
        ray.shutdown()
        return rval

    def get_custom(self, settings: SerializationSettings) -> Optional[Dict[str, Any]]:
        cfg = self._task_config

        ray_job = RayJob(
            ray_cluster=RayCluster(
                head_group_spec=HeadGroupSpec(cfg.head_node_config.ray_start_params) if cfg.head_node_config else None,
                worker_group_spec=[
                    WorkerGroupSpec(c.group_name, c.replicas, c.min_replicas, c.max_replicas, c.ray_start_params)
                    for c in cfg.worker_node_config
                ],
                namespace=cfg.namespace,
                k8s_sa=cfg.k8s_sa,
            ),
            # Use base64 to encode runtime_env dict and convert it to byte string
            runtime_env=base64.b64encode(json.dumps(cfg.runtime_env).encode()).decode(),
        )
        return MessageToDict(ray_job.to_flyte_idl())

    def get_config(self, settings: SerializationSettings) -> Dict[str, str]:
        return self._task_config.config_override or {}


# Inject the Ray plugin into flytekits dynamic plugin loading system
TaskPlugins.register_pythontask_plugin(RayJobConfig, RayFunctionTask)
