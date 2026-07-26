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

"""
Module to help with testing.
"""

import json


# one way to parameterize tests is to store the serialized state in a json file
# and then load it for the test.
def load_test_cases(file_name: str) -> tuple:
    """Load test cases from a json file."""
    with open(file_name, "r", encoding="utf-8") as f:
        json_test_cases = json.load(f)
        test_cases = [(tc.get("input_state"), tc.get("expected_state")) for tc in json_test_cases]
        test_ids = [
            f"{tc.get('action', 'ACTION_MISSING')}-{tc.get('name', 'NAME_MISSING')}"
            for tc in json_test_cases
        ]
    return test_cases, test_ids


# Define the pytest_generate_tests hook to generate test cases dynamically based on the
# contents of a file
def pytest_generate_tests(metafunc):
    """This function dynamically generates test cases based on the contents of a file.

    Use this with PyTest.
    """

    # for each function that has the 'input_state' and 'expected_state' arguments:
    if "input_state" in metafunc.fixturenames and "expected_state" in metafunc.fixturenames:
        # gets all filenames from the 'file_name' marker
        file_names = [
            file_arg
            for m in metafunc.definition.own_markers
            if m.name == "file_name"
            for file_arg in m.args
        ]
        all_test_cases = []
        all_test_ids = []
        for file_name in file_names:
            test_cases, test_case_ids = load_test_cases(file_name)
            all_test_cases.extend(test_cases)
            all_test_ids.extend(test_case_ids)
        if not all_test_cases:
            raise ValueError(
                f"No test cases could be created for test {metafunc.definition.originalname}."
            )
        # Generate test cases based on the test_data list
        metafunc.parametrize("input_state,expected_state", all_test_cases, ids=all_test_ids)
