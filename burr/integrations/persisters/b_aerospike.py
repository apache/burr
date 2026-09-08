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

import hashlib
import json
import random
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

from burr.core import persistence, state
from burr.integrations import base

if sys.version_info < (3, 10):
    raise ImportError(
        "The Aerospike persister requires Python 3.10 or newer. "
        "Install Burr with the 'aerospike' extra on a supported Python version."
    )

try:
    import aerospike
    import aerospike_helpers.expressions as expr
    from aerospike_helpers.operations import operations as aero_ops
except ImportError as e:
    base.require_plugin(e, "aerospike")

_CODE_VERSION = 1
_SYSTEM = "burr-as"

# Aerospike bin names are capped at 15 characters.
_PART_BIN = "partition"
_PREFIX_BIN = "key_prefix"
_TOKEN_BIN = "part_token"
_APP_BIN = "app_id"
_SEQ_BIN = "sequence_id"
_POS_BIN = "position"
_STATE_BIN = "state"
_STATUS_BIN = "status"
_CREATED_BIN = "created_at"

_MAX_WRITE_ATTEMPTS = 3
_RETRYABLE_CODES = {9, -10, 7, 14}  # Timeout, Connection, ClusterChange, KEY_BUSY


class AerospikePersistenceError(Exception):
    """Base class for Aerospike persister errors."""


class AerospikePersistenceConsistencyError(AerospikePersistenceError):
    """Raised when stored data violates the persister's invariants."""


class AerospikePersistenceInitializationError(AerospikePersistenceError):
    """Raised when secondary index initialization fails."""


class AerospikePersistenceSerializationError(AerospikePersistenceError, ValueError):
    """Raised when state cannot be serialized to strict JSON."""


class AerospikePersistenceUncertainOutcomeError(AerospikePersistenceError):
    """Raised when a write retry budget is exhausted without a definitive result."""


class AerospikePersister(persistence.BaseStatePersister):
    """Synchronous Aerospike-backed implementation of Burr's ``BaseStatePersister``.

    The persister stores one immutable history record per ``(partition_key,
    app_id, sequence_id)`` and a small mutable head record per ``(partition_key,
    app_id)`` that points to the latest sequence. Application IDs within a
    partition are listed through a string secondary index on the head set's
    fixed-size partition token.

    This optional integration requires Python 3.10+ and the official Aerospike
    Python client. Burr core remains compatible with Python 3.9+.
    """

    @classmethod
    def from_config(cls, config: dict) -> "AerospikePersister":
        """Create a persister from a configuration dictionary."""
        return cls.from_values(**config)

    @classmethod
    def from_values(
        cls,
        hosts: Optional[list] = None,
        client_config: Optional[dict] = None,
        namespace: str = "test",
        history_set: str = "burr_state",
        head_set: str = "burr_head",
        key_prefix: Optional[str] = "",
        serde_kwargs: Optional[dict] = None,
        index_name: str = "burr_head_partition_idx",
        create_index: bool = True,
    ) -> "AerospikePersister":
        """Create a persister from seed hosts and client configuration.

        :param hosts: Aerospike seed hosts as ``[(host, port), ...]``.
        :param client_config: Additional official client configuration options.
        :param namespace: Aerospike namespace.
        :param history_set: Set for immutable checkpoint records.
        :param head_set: Set for mutable latest-sequence heads.
        :param key_prefix: Optional logical prefix for key isolation.
        :param serde_kwargs: Kwargs for Burr ``State`` serialization.
        :param index_name: Name of the secondary index on the head set.
        :param create_index: Whether ``initialize()`` may create the index.
        """
        if hosts is None:
            hosts = [("127.0.0.1", 3000)]
        aerospike_config = {"hosts": hosts}
        if client_config:
            aerospike_config.update(client_config)

        client = aerospike.client(aerospike_config)

        return cls(
            client,
            namespace=namespace,
            history_set=history_set,
            head_set=head_set,
            key_prefix=key_prefix if key_prefix is not None else "",
            serde_kwargs=serde_kwargs,
            index_name=index_name,
            create_index=create_index,
            _client_config=aerospike_config,
            _owned=True,
        )

    def __init__(
        self,
        client,
        *,
        namespace: str = "test",
        history_set: str = "burr_state",
        head_set: str = "burr_head",
        key_prefix: Optional[str] = "",
        serde_kwargs: Optional[dict] = None,
        index_name: str = "burr_head_partition_idx",
        create_index: bool = True,
        _client_config: Optional[dict] = None,
        _owned: bool = False,
    ):
        """Initialize the persister with an Aerospike client.

        Direct construction accepts an already-connected caller-owned client.
        Use :meth:`from_values` or :meth:`from_config` for persister-owned
        clients.
        """
        self._client = client
        self._owned = _owned
        self.namespace = namespace
        self.history_set = history_set
        self.head_set = head_set
        self.key_prefix = key_prefix if key_prefix is not None else ""
        self.serde_kwargs = serde_kwargs or {}
        self.index_name = index_name
        self.create_index = create_index
        self._client_config = _client_config
        self._initialized = False
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.cleanup()
        return False

    def is_async(self) -> bool:
        return False

    def cleanup(self):
        """Close the persister-owned client, if any."""
        if self._owned and not self._closed and self._client is not None:
            self._client.close()
            self._closed = True

    def __getstate__(self) -> dict:
        if not self._owned:
            raise TypeError(
                "An AerospikePersister constructed with an injected client cannot be pickled"
            )
        if self._client_config is None:
            raise TypeError(
                "Cannot pickle an AerospikePersister without reconnectable client configuration"
            )
        state = self.__dict__.copy()
        del state["_client"]
        state["_initialized"] = False
        state["_closed"] = False
        return state

    def __setstate__(self, state: dict):
        client_config = state.get("_client_config")
        if client_config is None:
            raise TypeError("Cannot unpickle an AerospikePersister without client configuration")
        self.__dict__.update(state)
        try:
            self._client = aerospike.client(client_config)
        except Exception as e:
            raise AerospikePersistenceError(
                f"Failed to reconnect Aerospike client from configuration: {e}"
            ) from e
        self._owned = True
        self._initialized = False
        self._closed = False

    def set_serde_kwargs(self, serde_kwargs: dict):
        self.serde_kwargs = serde_kwargs

    def initialize(self):
        """Create the head-set secondary index if configured and wait for query readiness."""
        self._initialized = False
        if self.create_index:
            try:
                self._client.index_single_value_create(
                    self.namespace,
                    self.head_set,
                    _TOKEN_BIN,
                    aerospike.INDEX_STRING,
                    self.index_name,
                    {},
                )
            except aerospike.exception.IndexFoundError:
                pass
            except aerospike.exception.AerospikeError as e:
                raise AerospikePersistenceInitializationError(
                    f"Failed to create secondary index '{self.index_name}': {e}"
                ) from e

        deadline = time.monotonic() + 30.0
        attempt = 0
        while True:
            try:
                self._app_id_query("").results()
            except (aerospike.exception.IndexNotFound, aerospike.exception.IndexNotReadable) as e:
                if time.monotonic() >= deadline:
                    raise AerospikePersistenceInitializationError(
                        "Timed out waiting for the secondary index to become queryable"
                    ) from e
                attempt += 1
                self._backoff(attempt)
                continue
            except aerospike.exception.AerospikeError as e:
                raise AerospikePersistenceInitializationError(
                    f"Failed to verify secondary-index query readiness: {e}"
                ) from e
            self._initialized = True
            return

    def is_initialized(self) -> bool:
        return self._initialized

    def save(
        self,
        partition_key: Optional[str],
        app_id: str,
        sequence_id: int,
        position: str,
        state: state.State,
        status: str,
        **kwargs,
    ):
        self._validate_sequence_id(sequence_id)

        try:
            state_json = json.dumps(state.serialize(**self.serde_kwargs), allow_nan=False)
        except (TypeError, ValueError) as e:
            raise AerospikePersistenceSerializationError(
                f"State is not JSON-serializable: {e}"
            ) from e
        created_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")

        key_prefix = self.key_prefix
        partition_canonical = self._canonical_partition(partition_key)
        key_prefix_canonical = self._canonical_key_prefix()
        part_token = self._derive_partition_token(key_prefix, partition_key)

        history_key = self._key(
            self.history_set,
            self._derive_history_key(key_prefix, partition_key, app_id, sequence_id),
        )
        head_key = self._key(
            self.head_set,
            self._derive_head_key(key_prefix, partition_key, app_id),
        )

        history_bins = {
            _PART_BIN: partition_canonical,
            _PREFIX_BIN: key_prefix_canonical,
            _APP_BIN: app_id,
            _SEQ_BIN: sequence_id,
            _POS_BIN: position,
            _STATE_BIN: state_json,
            _STATUS_BIN: status,
            _CREATED_BIN: created_at,
        }

        # History must exist before the head can be advanced.
        self._write_history(history_key, history_bins)

        head_bins = {
            _PART_BIN: partition_canonical,
            _PREFIX_BIN: key_prefix_canonical,
            _TOKEN_BIN: part_token,
            _APP_BIN: app_id,
            _SEQ_BIN: sequence_id,
        }
        self._advance_head(head_key, head_bins)

    def load(
        self,
        partition_key: Optional[str],
        app_id: Optional[str],
        sequence_id: Optional[int] = None,
        **kwargs,
    ) -> Optional[persistence.PersistedStateData]:
        if app_id is None:
            raise ValueError("app_id is required for load")
        if sequence_id is not None:
            self._validate_sequence_id(sequence_id)

        if sequence_id is None:
            return self._load_latest(partition_key, app_id)

        # Exact-sequence load.
        key_prefix = self.key_prefix
        partition_canonical = self._canonical_partition(partition_key)
        key_prefix_canonical = self._canonical_key_prefix()
        history_key = self._key(
            self.history_set,
            self._derive_history_key(key_prefix, partition_key, app_id, sequence_id),
        )
        history_record = self._read_history(history_key)
        if history_record is None:
            return None
        self._validate_history_identity(
            history_record, partition_canonical, key_prefix_canonical, app_id, sequence_id
        )
        return self._build_persisted_data(history_record, partition_key, app_id, sequence_id)

    def _load_latest(
        self,
        partition_key: Optional[str],
        app_id: str,
    ) -> Optional[persistence.PersistedStateData]:
        """Load the latest state for an application by reading the head, then the referenced history."""
        key_prefix = self.key_prefix
        partition_canonical = self._canonical_partition(partition_key)
        key_prefix_canonical = self._canonical_key_prefix()
        head_key = self._key(
            self.head_set,
            self._derive_head_key(key_prefix, partition_key, app_id),
        )
        head_record = self._read_head(head_key)
        if head_record is None:
            return None
        stored_seq = self._validate_head_identity(
            head_record,
            partition_canonical,
            key_prefix_canonical,
            app_id,
            self._derive_partition_token(key_prefix, partition_key),
        )
        history_key = self._key(
            self.history_set,
            self._derive_history_key(key_prefix, partition_key, app_id, stored_seq),
        )
        history_record = self._read_history(history_key)
        if history_record is None:
            raise AerospikePersistenceConsistencyError(
                f"Head for app_id={app_id} references missing history sequence {stored_seq}"
            )
        self._validate_history_identity(
            history_record, partition_canonical, key_prefix_canonical, app_id, stored_seq
        )
        return self._build_persisted_data(history_record, partition_key, app_id, stored_seq)

    def list_app_ids(self, partition_key: Optional[str], **kwargs) -> list[str]:
        part_token = self._derive_partition_token(self.key_prefix, partition_key)
        try:
            results = self._app_id_query(part_token).results()
        except (aerospike.exception.IndexNotFound, aerospike.exception.IndexNotReadable) as e:
            raise AerospikePersistenceInitializationError(
                "The head-set secondary index is not ready; call initialize()"
            ) from e
        except aerospike.exception.AerospikeError as e:
            raise AerospikePersistenceError(f"Application listing query failed: {e}") from e

        app_ids = {bins[_APP_BIN] for _, _, bins in results}
        return list(app_ids)

    def _canonical_json(self, value: Any) -> str:
        """Deterministic JSON encoding used for canonical identities and state snapshots."""
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def _identity_history(
        self, key_prefix: Optional[str], partition_key: Optional[str], app_id: str, sequence_id: int
    ) -> list:
        return [
            _SYSTEM,
            _CODE_VERSION,
            "history",
            key_prefix,
            partition_key,
            app_id,
            sequence_id,
        ]

    def _identity_head(
        self, key_prefix: Optional[str], partition_key: Optional[str], app_id: str
    ) -> list:
        return [
            _SYSTEM,
            _CODE_VERSION,
            "head",
            key_prefix,
            partition_key,
            app_id,
        ]

    def _identity_partition(self, key_prefix: Optional[str], partition_key: Optional[str]) -> list:
        return [
            _SYSTEM,
            _CODE_VERSION,
            "partition",
            key_prefix,
            partition_key,
        ]

    def _sha256_hex(self, data: str) -> str:
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    def _derive_history_key(
        self, key_prefix: Optional[str], partition_key: Optional[str], app_id: str, sequence_id: int
    ) -> str:
        return self._sha256_hex(
            self._canonical_json(
                self._identity_history(key_prefix, partition_key, app_id, sequence_id)
            )
        )

    def _derive_head_key(
        self, key_prefix: Optional[str], partition_key: Optional[str], app_id: str
    ) -> str:
        return self._sha256_hex(
            self._canonical_json(self._identity_head(key_prefix, partition_key, app_id))
        )

    def _derive_partition_token(
        self, key_prefix: Optional[str], partition_key: Optional[str]
    ) -> str:
        return self._sha256_hex(
            self._canonical_json(self._identity_partition(key_prefix, partition_key))
        )

    def _validate_sequence_id(self, sequence_id: Any) -> None:
        if type(sequence_id) is not int or isinstance(sequence_id, bool):
            raise ValueError(
                f"sequence_id must be a 64-bit signed integer, got {sequence_id!r} (type {type(sequence_id).__name__})"
            )
        if sequence_id < -(2**63) or sequence_id > 2**63 - 1:
            raise ValueError(
                f"sequence_id {sequence_id} is outside the signed 64-bit integer range"
            )

    def _key(self, set_name: str, user_key: str):
        return (self.namespace, set_name, user_key)

    def _canonical_partition(self, partition_key: Optional[str]) -> str:
        return self._canonical_json(partition_key)

    def _canonical_key_prefix(self) -> str:
        return self._canonical_json(self.key_prefix)

    def _read_record(self, key, policy=None):
        read_policy = policy or {"replica": aerospike.POLICY_REPLICA_MASTER}
        try:
            return self._client.get(key, policy=read_policy)
        except aerospike.exception.RecordNotFound:
            return None

    def _is_retryable(self, exc: aerospike.exception.AerospikeError) -> bool:
        return getattr(exc, "code", None) in _RETRYABLE_CODES

    def _backoff(self, attempt: int) -> None:
        # Bounded exponential backoff with jitter (seconds).
        delay = min(0.05 * (2**attempt), 1.0)
        time.sleep(delay * (0.5 + random.random()))

    def _read_history(self, key):
        record = self._read_record(key)
        if record is None:
            return None
        _, _, bins = record
        return bins

    def _read_head(self, key):
        return self._read_history(key)

    def _write_history_once(self, history_key, bins):
        """Attempt one create-only history write."""
        try:
            self._client.put(
                history_key,
                bins,
                policy={
                    "commit_level": aerospike.POLICY_COMMIT_LEVEL_ALL,
                    "exists": aerospike.POLICY_EXISTS_CREATE,
                    "ttl": aerospike.TTL_NEVER_EXPIRE,
                },
            )
        except aerospike.exception.RecordTooBig as e:
            raise AerospikePersistenceSerializationError(
                "Checkpoint record exceeds the namespace max-record-size"
            ) from e

    def _write_history(self, history_key, bins):
        """Create-only history write with bounded retries."""
        for attempt in range(1, _MAX_WRITE_ATTEMPTS + 1):
            try:
                self._write_history_once(history_key, bins)
                return None
            except aerospike.exception.RecordExistsError:
                # The checkpoint already exists; history is immutable, so this is idempotent.
                return None
            except aerospike.exception.AerospikeError as e:
                if self._is_retryable(e):
                    # Reconcile: if the record is now present, the write succeeded.
                    existing = self._read_history(history_key)
                    if existing is not None:
                        return existing
                    if attempt == _MAX_WRITE_ATTEMPTS:
                        raise AerospikePersistenceUncertainOutcomeError(
                            "History write timed out or failed with an uncertain outcome"
                        ) from e
                    self._backoff(attempt)
                    continue
                raise AerospikePersistenceError(f"History write failed: {e}") from e

        raise AerospikePersistenceUncertainOutcomeError("History write retry budget exhausted")

    def _head_filter_expression(
        self,
        partition_canonical: str,
        key_prefix_canonical: str,
        app_id: str,
        part_token: str,
        sequence_id: int,
    ):
        """Build a conditional expression for the head operate().

        The operation is allowed when the record does not exist, or when the
        existing record has the same identity and a lower stored sequence.
        """
        return expr.Or(
            expr.Not(expr.BinExists(_SEQ_BIN)),
            expr.And(
                expr.Eq(expr.StrBin(_PART_BIN), partition_canonical),
                expr.Eq(expr.StrBin(_PREFIX_BIN), key_prefix_canonical),
                expr.Eq(expr.StrBin(_APP_BIN), app_id),
                expr.Eq(expr.StrBin(_TOKEN_BIN), part_token),
                expr.LT(expr.IntBin(_SEQ_BIN), sequence_id),
            ),
        ).compile()

    def _head_ops(self, bins: dict):
        """Return operate() ops that write all head bins and read the sequence."""
        return [
            aero_ops.write(_PART_BIN, bins[_PART_BIN]),
            aero_ops.write(_PREFIX_BIN, bins[_PREFIX_BIN]),
            aero_ops.write(_TOKEN_BIN, bins[_TOKEN_BIN]),
            aero_ops.write(_APP_BIN, bins[_APP_BIN]),
            aero_ops.write(_SEQ_BIN, bins[_SEQ_BIN]),
            aero_ops.read(_SEQ_BIN),
        ]

    def _validate_head_identity(
        self,
        bins: dict,
        partition_canonical: str,
        key_prefix_canonical: str,
        app_id: str,
        part_token: str,
    ) -> int:
        """Validate that a head record's identity matches the request.

        Returns the stored sequence_id or raises AerospikePersistenceConsistencyError.
        """
        if bins.get(_PART_BIN) != partition_canonical:
            raise AerospikePersistenceConsistencyError(
                "Head record partition identity does not match the requested identity"
            )
        if bins.get(_PREFIX_BIN) != key_prefix_canonical:
            raise AerospikePersistenceConsistencyError(
                "Head record key_prefix does not match the requested key_prefix"
            )
        if bins.get(_TOKEN_BIN) != part_token:
            raise AerospikePersistenceConsistencyError("Head record partition token is corrupted")
        if bins.get(_APP_BIN) != app_id:
            raise AerospikePersistenceConsistencyError(
                "Head record app_id does not match the requested app_id"
            )
        stored_seq = bins[_SEQ_BIN]
        self._validate_sequence_id(stored_seq)
        return stored_seq

    def _advance_head(
        self,
        head_key,
        head_bins: dict,
    ):
        """Atomically create or advance the application head.

        Uses a conditional operate() with server-side filtering. A filtered or
        ambiguous result is classified through a correctness-sensitive master
        read before any retry or final decision.
        """
        sequence_id = head_bins[_SEQ_BIN]
        partition_canonical = head_bins[_PART_BIN]
        key_prefix_canonical = head_bins[_PREFIX_BIN]
        app_id = head_bins[_APP_BIN]
        part_token = head_bins[_TOKEN_BIN]

        ops = self._head_ops(head_bins)
        filter_expr = self._head_filter_expression(
            partition_canonical, key_prefix_canonical, app_id, part_token, sequence_id
        )

        for attempt in range(1, _MAX_WRITE_ATTEMPTS + 1):
            try:
                _, _, result_bins = self._client.operate(
                    head_key,
                    ops,
                    policy={
                        "commit_level": aerospike.POLICY_COMMIT_LEVEL_ALL,
                        "expressions": filter_expr,
                        "ttl": aerospike.TTL_NEVER_EXPIRE,
                    },
                )
            except aerospike.exception.FilteredOut:
                # The record exists and the condition was false. Read and classify.
                existing = self._read_head(head_key)
                if existing is None:
                    if attempt == _MAX_WRITE_ATTEMPTS:
                        raise AerospikePersistenceUncertainOutcomeError(
                            "Head update was filtered out but the record could not be reconciled"
                        )
                    self._backoff(attempt)
                    continue
                stored_seq = self._validate_head_identity(
                    existing, partition_canonical, key_prefix_canonical, app_id, part_token
                )
                if stored_seq >= sequence_id:
                    return existing
                # Stored sequence is lower than requested but filter was false:
                # a concurrent writer may have changed the record, retry.
                if attempt == _MAX_WRITE_ATTEMPTS:
                    raise AerospikePersistenceUncertainOutcomeError(
                        "Head update could not be reconciled within the retry budget"
                    )
                self._backoff(attempt)
                continue
            except aerospike.exception.AerospikeError as e:
                if self._is_retryable(e):
                    existing = self._read_head(head_key)
                    if existing is not None:
                        stored_seq = self._validate_head_identity(
                            existing,
                            partition_canonical,
                            key_prefix_canonical,
                            app_id,
                            part_token,
                        )
                        if stored_seq >= sequence_id:
                            return existing
                    if attempt == _MAX_WRITE_ATTEMPTS:
                        raise AerospikePersistenceUncertainOutcomeError(
                            "Head update failed with an uncertain outcome"
                        ) from e
                    self._backoff(attempt)
                    continue
                raise AerospikePersistenceError(f"Head update failed: {e}") from e

            stored_seq = result_bins[_SEQ_BIN]
            self._validate_sequence_id(stored_seq)
            if stored_seq < sequence_id:
                raise AerospikePersistenceConsistencyError(
                    "Head operate returned a sequence lower than the requested sequence"
                )
            return result_bins

        raise AerospikePersistenceUncertainOutcomeError("Head update retry budget exhausted")

    def _validate_history_identity(
        self,
        bins: dict,
        partition_canonical: str,
        key_prefix_canonical: str,
        app_id: str,
        sequence_id: int,
    ):
        stored_seq = bins[_SEQ_BIN]
        self._validate_sequence_id(stored_seq)

        if bins[_PREFIX_BIN] != key_prefix_canonical:
            raise AerospikePersistenceConsistencyError(
                "History record key_prefix does not match the requested key_prefix"
            )
        if bins[_PART_BIN] != partition_canonical:
            raise AerospikePersistenceConsistencyError(
                "History record partition identity does not match the requested identity"
            )
        if bins[_APP_BIN] != app_id:
            raise AerospikePersistenceConsistencyError(
                "History record app_id does not match the requested app_id"
            )
        if bins[_SEQ_BIN] != sequence_id:
            raise AerospikePersistenceConsistencyError(
                "History record sequence_id does not match the requested sequence_id"
            )

    def _build_persisted_data(
        self,
        history_bins: dict,
        partition_key: Optional[str],
        app_id: str,
        sequence_id: int,
    ) -> persistence.PersistedStateData:
        return {
            "partition_key": partition_key,
            "app_id": app_id,
            "sequence_id": sequence_id,
            "position": history_bins[_POS_BIN],
            "state": state.State.deserialize(
                json.loads(history_bins[_STATE_BIN]), **self.serde_kwargs
            ),
            "created_at": history_bins[_CREATED_BIN],
            "status": history_bins[_STATUS_BIN],
        }

    def _app_id_query(self, part_token: str):
        query = self._client.query(self.namespace, self.head_set)
        query.select(_APP_BIN)
        query.where(aerospike.predicates.equals(_TOKEN_BIN, part_token))
        return query
