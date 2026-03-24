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

import inspect
from typing import Any, AsyncGenerator, AsyncIterable, Coroutine, Generator, List, TypeVar, Union

T = TypeVar("T")

GenType = TypeVar("GenType")

SyncOrAsyncIterable = Union[AsyncIterable[T], List[T]]
SyncOrAsyncGenerator = Union[Generator[GenType, None, None], AsyncGenerator[GenType, None]]
SyncOrAsyncGeneratorOrItemOrList = Union[SyncOrAsyncGenerator[GenType], List[GenType], GenType]


class _AsyncPersisterContextManager:
    """Wraps an async coroutine that returns a persister so it can be used
    directly with ``async with``::

        async with AsyncSQLitePersister.from_values(...) as persister:
            ...

    The wrapper awaits the coroutine on ``__aenter__`` and delegates
    ``__aexit__`` to the persister's own ``__aexit__``.

    .. note::
        Each instance wraps a single coroutine and can only be consumed once,
        either via ``await`` or ``async with``. A second use will raise
        ``RuntimeError``.
    """

    def __init__(self, coro: Coroutine[Any, Any, Any]):
        self._coro = coro
        self._persister = None
        self._consumed = False

    def __await__(self):
        if self._consumed:
            raise RuntimeError("This factory result has already been consumed")
        self._consumed = True
        return self._coro.__await__()

    async def __aenter__(self):
        if self._consumed:
            raise RuntimeError("This factory result has already been consumed")
        self._consumed = True
        self._persister = await self._coro
        return await self._persister.__aenter__()

    async def __aexit__(self, exc_type, exc_value, traceback):
        if self._persister is None:
            return False
        return await self._persister.__aexit__(exc_type, exc_value, traceback)


async def asyncify_generator(
    generator: SyncOrAsyncGenerator[GenType],
) -> AsyncGenerator[GenType, None]:
    """Convert a sync generator to an async generator.

    :param generator: sync generator
    :return: async generator
    """
    if inspect.isasyncgen(generator):
        async for item in generator:
            yield item
    else:
        for item in generator:
            yield item


async def arealize(maybe_async_generator: SyncOrAsyncGenerator[GenType]) -> List[GenType]:
    """Realize an async generator or async iterable to a list.

    :param maybe_async_generator: async generator or async iterable
    :return: list of items -- fully realized
    """
    if inspect.isasyncgen(maybe_async_generator):
        out = [item async for item in maybe_async_generator]
    else:
        out = [item for item in maybe_async_generator]
    return out
