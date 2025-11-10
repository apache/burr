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
import sys

import pytest
from langchain_community.document_transformers.embeddings_redundant_filter import _DocumentWithState
from langchain_core import documents as lc_documents
from langchain_core import messages as lc_messages

from burr.core import serde, state


def test_serde_of_lc_document():
    doc = lc_documents.Document(page_content="test content")
    og = state.State({"doc": doc})
    serialized = og.serialize()
    assert serialized == {
        "doc": {
            serde.KEY: "lc_document",
            "id": ["langchain", "schema", "document", "Document"],
            "kwargs": {"page_content": "test content", "type": "Document"},
            "lc": 1,
            "type": "constructor",
        }
    }
    ng = state.State.deserialize(serialized)
    assert isinstance(ng["doc"], lc_documents.Document)
    assert ng["doc"].page_content == "test content"
    assert serde.KEY not in ng


@pytest.mark.skipif(sys.version_info < (3, 10), reason="requires python3.10 or higher")
def test_serde_of_lc_message():
    message = lc_messages.HumanMessage(content="test content")
    og = state.State({"message": message})
    serialized = og.serialize()
    assert serialized == {
        "message": {
            serde.KEY: "lc_message",
            "data": {
                "additional_kwargs": {},
                "content": "test content",
                "id": None,
                "name": None,
                "response_metadata": {},
                "type": "human",
            },
            "type": "human",
        }
    }
    ng = state.State.deserialize(serialized)
    assert isinstance(ng["message"], lc_messages.HumanMessage)
    assert ng["message"].content == "test content"
    assert serde.KEY not in ng


def test_serde_of_document_with_state():
    """Tests that we can serialize a document that is not serializable to a document."""
    doc = _DocumentWithState(page_content="Hello, World document with state!", state={"foo": "bar"})
    og = state.State({"doc": doc})
    serialized = og.serialize()
    assert serialized == {
        "doc": {
            serde.KEY: "lc_document_with_state",
            "doc": {
                serde.KEY: "lc_document",
                "id": ["langchain", "schema", "document", "Document"],
                "kwargs": {"page_content": "Hello, World document with state!", "type": "Document"},
                "lc": 1,
                "type": "constructor",
            },
            "state": {"foo": "bar"},
        }
    }
    ng = state.State.deserialize(serialized)
    assert isinstance(ng["doc"], lc_documents.Document)
    assert ng["doc"].page_content == "Hello, World document with state!"
    assert serde.KEY not in ng
