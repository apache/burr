# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements...


import pytest
from burr.core.action import action
from burr.core.state import State


def test_undeclared_state_read_raises_error():
    with pytest.raises(ValueError):

        @action(reads=["foo"], writes=[])
        def bad_action(state: State):
            x = state["bar"]
            return {}, state


def test_declared_state_read_passes():
    @action(reads=["foo"], writes=[])
    def good_action(state: State):
        x = state["foo"]
        return {}, state
