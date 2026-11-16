# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Serde for test_burr_ray.py, in its own module so that Ray workers import it -- and thereby
register the serializers -- when unpickling the actions that use it."""

from burr.core import ApplicationContext, State, action, serde
from burr.core.artifacts import ArtifactRef
from burr.core.serde import SerializationContext
from burr.core.state import register_field_serde

REPORT_FIELD = "ray_externalized_report"


class RayBlob:
    """Lazily-loadable value externalized by type-based serde."""

    def __init__(self, data: bytes = None, ref: ArtifactRef = None, store=None):
        self._data, self.ref, self._store = data, ref, store

    @property
    def data(self) -> bytes:
        if self._data is None:
            if self._store is None:
                raise ValueError("RayBlob was loaded without an object store.")
            self._data = self.ref.read(self._store)
        return self._data


@serde.serialize.register(RayBlob)
def _serialize_ray_blob(value: RayBlob, serialization_context: SerializationContext, **kwargs):
    ref = value.ref or serialization_context.require_object_store().put_artifact(value.data)
    return {serde.KEY: "ray_blob", "ref": serde.serialize(ref)}


@serde.deserializer.register("ray_blob")
def _deserialize_ray_blob(
    value: dict, serialization_context: SerializationContext = None, **kwargs
) -> RayBlob:
    store = serialization_context.object_store if serialization_context is not None else None
    return RayBlob(ref=serde.deserialize(value["ref"]), store=store)


def _serialize_report(value: str, serialization_context: SerializationContext, **kwargs) -> dict:
    ref = serialization_context.require_object_store().put_artifact(value.encode())
    return {"ref": serde.serialize(ref)}


def _deserialize_report(value: dict, serialization_context: SerializationContext, **kwargs) -> str:
    return (
        serde.deserialize(value["ref"]).read(serialization_context.require_object_store()).decode()
    )


register_field_serde(REPORT_FIELD, _serialize_report, _deserialize_report)


@action(reads=["n"], writes=["blob", REPORT_FIELD])
def produce(state: State) -> State:
    return state.update(
        blob=RayBlob(b"blob-%d" % state["n"]), **{REPORT_FIELD: f"report-{state['n']}"}
    )


@action(reads=["blob", REPORT_FIELD], writes=["summary", "loaded_lazily"])
def summarize(state: State, __context: ApplicationContext) -> State:
    # runs on the worker after the child app reloaded its state from the persister
    return state.update(
        summary=f"{state['blob'].data.decode()}|{state[REPORT_FIELD]}",
        loaded_lazily=isinstance(state["blob"], RayBlob) and state["blob"].ref is not None,
    )
