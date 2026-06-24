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

"""This module will be deprecated. Please use b_pymongo.py for imports."""

import logging

from pymongo import MongoClient

from burr.integrations.persisters.b_pymongo import (
    _DRIVER_INFO,
)
from burr.integrations.persisters.b_pymongo import MongoDBBasePersister as PymongoPersister

logger = logging.getLogger(__name__)

logger.warning(
    "This class is deprecated and has been moved. "
    "Please import MongoDBBasePersister from b_pymongo.py."
)


class MongoDBBasePersister(PymongoPersister):
    """A class used to represent the MongoDB Persister.

    This class is deprecated and has been moved to b_pymongo.py.
    """

    @classmethod
    def from_values(
        cls,
        uri="mongodb://localhost:27017",
        db_name="mydatabase",
        collection_name="mystates",
        serde_kwargs: dict = None,
        mongo_client_kwargs: dict = None,
    ) -> "MongoDBBasePersister":
        """Initializes the MongoDBBasePersister class."""

        if mongo_client_kwargs is None:
            mongo_client_kwargs = {}
        mongo_client_kwargs.setdefault("driver", _DRIVER_INFO)
        client = MongoClient(uri, **mongo_client_kwargs)
        return PymongoPersister(
            client=client,
            db_name=db_name,
            collection_name=collection_name,
            serde_kwargs=serde_kwargs,
        )


class MongoDBPersister(PymongoPersister):
    """A class used to represent a MongoDB Persister.

    This class is deprecated. Please use MongoDBBasePersister instead.
    """

    def __init__(
        self,
        uri="mongodb://localhost:27017",
        db_name="mydatabase",
        collection_name="mystates",
        serde_kwargs: dict = None,
        mongo_client_kwargs: dict = None,
    ):
        """Initializes the MongoDBPersister class."""
        if mongo_client_kwargs is None:
            mongo_client_kwargs = {}
        mongo_client_kwargs.setdefault("driver", _DRIVER_INFO)
        client = MongoClient(uri, **mongo_client_kwargs)
        super(MongoDBPersister, self).__init__(
            client=client,
            db_name=db_name,
            collection_name=collection_name,
            serde_kwargs=serde_kwargs,
        )
