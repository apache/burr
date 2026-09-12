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

from burr.integrations import base

try:
    import gspread
except ImportError as e:
    base.require_plugin(e, "google-sheets")

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from burr.core import persistence, state

logger = logging.getLogger(__name__)

COLUMNS = [
    "partition_key",
    "app_id",
    "sequence_id",
    "position",
    "state",
    "created_at",
    "status",
]

_PARTITION_KEY = 0
_APP_ID = 1
_SEQUENCE_ID = 2
_POSITION = 3
_STATE = 4
_CREATED_AT = 5
_STATUS = 6


def _encode_partition_key(partition_key: Optional[str]) -> str:
    """Google Sheets has no concept of null, so ``None`` is stored as an empty cell."""
    return "" if partition_key is None else partition_key


class GoogleSheetsBasePersister(persistence.BaseStatePersister):
    """Persister that stores state in a Google Sheets worksheet.

    .. warning::
        This persister is in **beta**. Google Sheets is not a database -- the Sheets API
        enforces per-user quotas (on the order of 60 reads and 300 writes per minute), every
        value is stored as a string, and there are no indexes, so reads scan the whole
        worksheet. It is intended for demos, prototypes, and low-volume applications where
        a human-readable, shareable store is worth more than throughput.

    Each saved step is appended as a single row. The first row of the worksheet is a header
    (see :py:data:`COLUMNS`), written by :py:meth:`initialize`, and is skipped by every read.

    Use this class directly if you want to control the ``gspread`` worksheet object yourself,
    or use :py:meth:`from_values` to build one from a service account file.
    """

    @classmethod
    def from_config(cls, config: dict) -> "GoogleSheetsBasePersister":
        """Creates a new instance of the GoogleSheetsBasePersister from a configuration dictionary."""
        return cls.from_values(**config)

    @classmethod
    def from_values(
        cls,
        service_account_file: str,
        spreadsheet_key: str,
        worksheet_name: str = "Sheet1",
        serde_kwargs: dict = None,
    ) -> "GoogleSheetsBasePersister":
        """Creates a new instance of the GoogleSheetsBasePersister from passed in values.

        :param service_account_file: path to a Google service account JSON key file. The
            service account must have edit access to the target spreadsheet.
        :param spreadsheet_key: the spreadsheet ID, i.e. the ``<key>`` in
            ``https://docs.google.com/spreadsheets/d/<key>/edit``.
        :param worksheet_name: the worksheet (tab) within the spreadsheet to use.
        :param serde_kwargs: serialization and deserialization keyword arguments to pass to state SERDE.
        """
        client = gspread.service_account(filename=service_account_file)
        worksheet = client.open_by_key(spreadsheet_key).worksheet(worksheet_name)
        return cls(worksheet, serde_kwargs)

    def __init__(self, worksheet: Any, serde_kwargs: dict = None):
        """Initializes the GoogleSheetsBasePersister class.

        :param worksheet: a ``gspread`` worksheet object to read and write.
        :param serde_kwargs: serialization and deserialization keyword arguments to pass to state SERDE.
        """
        self.worksheet = worksheet
        self.serde_kwargs = serde_kwargs or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def set_serde_kwargs(self, serde_kwargs: dict):
        """Sets the serde_kwargs for the persister."""
        self.serde_kwargs = serde_kwargs

    def initialize(self):
        """Writes the header row if the worksheet does not already have one.

        This is idempotent -- calling it on an initialized worksheet is a no-op.
        """
        if self.is_initialized():
            return
        self.worksheet.append_row(COLUMNS)

    def is_initialized(self) -> bool:
        """Whether the worksheet has the expected header row."""
        rows = self.worksheet.get_all_values()
        return bool(rows) and rows[0] == COLUMNS

    def _data_rows(self) -> list[list[str]]:
        """Returns the worksheet rows with the header stripped.

        Every read goes through here so that the header is skipped consistently.
        """
        rows = self.worksheet.get_all_values()
        if rows and rows[0] == COLUMNS:
            return rows[1:]
        return rows

    def list_app_ids(self, partition_key: str, **kwargs) -> list[str]:
        """List the app ids for a given partition key, most recently written first."""
        encoded = _encode_partition_key(partition_key)
        last_written = {}
        for index, row in enumerate(self._data_rows()):
            if len(row) < len(COLUMNS) or row[_PARTITION_KEY] != encoded:
                continue
            last_written[row[_APP_ID]] = index
        return [
            app_id
            for app_id, _ in sorted(last_written.items(), key=lambda item: item[1], reverse=True)
        ]

    def load(
        self, partition_key: str, app_id: str, sequence_id: int = None, **kwargs
    ) -> Optional[persistence.PersistedStateData]:
        """Load the state data for a given partition key, app id, and sequence id.

        If ``sequence_id`` is not given, the state of the most recently written row for this
        app is returned. Because rows are only ever appended, the *last* matching row is
        always the current one -- earlier rows are prior steps.

        :param partition_key:
        :param app_id:
        :param sequence_id:
        :param kwargs:
        :return: PersistedStateData or None if no matching row exists.
        """
        encoded = _encode_partition_key(partition_key)
        match = None
        for row in self._data_rows():
            if len(row) < len(COLUMNS):
                continue
            if row[_PARTITION_KEY] != encoded or row[_APP_ID] != app_id:
                continue
            if sequence_id is not None and row[_SEQUENCE_ID] != str(sequence_id):
                continue
            match = row  # keep scanning; the last match wins
        if match is None:
            return None
        _state = state.State.deserialize(json.loads(match[_STATE]), **self.serde_kwargs)
        return {
            "partition_key": partition_key,
            "app_id": match[_APP_ID],
            "sequence_id": int(match[_SEQUENCE_ID]),
            "position": match[_POSITION],
            "state": _state,
            "created_at": match[_CREATED_AT],
            "status": match[_STATUS],
        }

    def save(
        self,
        partition_key: Optional[str],
        app_id: str,
        sequence_id: int,
        position: str,
        state: state.State,
        status: Literal["completed", "failed"],
        **kwargs,
    ):
        """Append the state data as a new row in the worksheet.

        :param partition_key:
        :param app_id:
        :param sequence_id:
        :param position:
        :param state:
        :param status:
        :param kwargs:
        :raises ValueError: if a row for this (partition_key, app_id, sequence_id, position)
            already exists.
        """
        encoded = _encode_partition_key(partition_key)
        for row in self._data_rows():
            if len(row) < len(COLUMNS):
                continue
            if (
                row[_PARTITION_KEY] == encoded
                and row[_APP_ID] == app_id
                and row[_SEQUENCE_ID] == str(sequence_id)
                and row[_POSITION] == position
            ):
                raise ValueError(
                    f"partition_key:app_id:sequence_id:position"
                    f"[{encoded}:{app_id}:{sequence_id}:{position}] already exists."
                )
        json_state = json.dumps(state.serialize(**self.serde_kwargs))
        self.worksheet.append_row(
            [
                encoded,
                app_id,
                str(sequence_id),
                position,
                json_state,
                datetime.now(timezone.utc).isoformat(),
                status,
            ]
        )

    def cleanup(self):
        """No-op -- the Google Sheets client holds no long-lived connection to close."""
        pass
