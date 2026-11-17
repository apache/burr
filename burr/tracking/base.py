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

import abc

from burr.lifecycle import (
    PostApplicationCreateHook,
    PostEndSpanHook,
    PostRunStepHook,
    PreRunStepHook,
    PreStartSpanHook,
)
from burr.lifecycle.base import (
    DoLogAttributeHook,
    PostEndStreamHook,
    PostStreamItemHook,
    PreStartStreamHook,
)


class SyncTrackingClient(
    PostApplicationCreateHook,
    PreRunStepHook,
    PostRunStepHook,
    PreStartSpanHook,
    PostEndSpanHook,
    DoLogAttributeHook,
    PreStartStreamHook,
    PostStreamItemHook,
    PostEndStreamHook,
    abc.ABC,
):
    """Base class for synchronous tracking clients. All tracking clients must implement from this.

    This registers the *synchronous* lifecycle hooks, so an instance is called from both
    synchronous and asynchronous applications -- asynchronous execution methods dispatch the
    sync and async hook families together (see
    :py:meth:`~burr.lifecycle.internal.LifecycleAdapterSet.call_all_lifecycle_hooks_sync_and_async`).
    For a tracker whose step hooks must ``await``, see :py:class:`AsyncTrackingClient`.
    """

    @abc.abstractmethod
    def copy(self):
        pass


TrackingClient = SyncTrackingClient


class AsyncTrackingClient(abc.ABC):
    """Marker base class for tracking clients whose step hooks are asynchronous.

    This is deliberately **not** a subclass of :py:class:`SyncTrackingClient`. A class must not
    inherit both families of step hooks: asynchronous applications dispatch *both* the synchronous
    and the asynchronous hooks, so an adapter registered under both would log every step twice.

    Implementations therefore inherit the asynchronous step hooks
    (:py:class:`~burr.lifecycle.base.PreRunStepHookAsync` /
    :py:class:`~burr.lifecycle.base.PostRunStepHookAsync`) and leave the remaining hooks on their
    synchronous base classes, matching how Burr dispatches them:

    * ``pre_run_step`` / ``post_run_step`` / ``pre_start_stream`` / ``post_stream_item`` /
      ``post_end_stream`` are dispatched to **both** families, so they must only ever be
      registered once.
    * ``post_application_create``, ``pre_start_span``, ``post_end_span`` and ``do_log_attributes``
      are only dispatched synchronously (span events also arrive from the OpenTelemetry span
      processor), so they stay synchronous.
    """

    @abc.abstractmethod
    def copy(self):
        """Clones the tracking client, so that forked/spawned/parallel applications do not share
        per-application mutable tracking state (the open log file handle, stream state, ...).

        :return: a fresh tracking client with the same configuration.
        """
        pass
