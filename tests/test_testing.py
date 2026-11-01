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

import json

from burr.testing import load_test_cases


def test_load_test_cases_reads_utf8_json(tmp_path):
    test_case_file = tmp_path / "test_cases.json"
    test_case_file.write_text(
        json.dumps(
            [
                {
                    "action": "summarize",
                    "name": "handles_utf8",
                    "input_state": {"message": "café"},
                    "expected_state": {"response": "résumé"},
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    test_cases, test_ids = load_test_cases(str(test_case_file))

    assert test_cases == [({"message": "café"}, {"response": "résumé"})]
    assert test_ids == ["summarize-handles_utf8"]
