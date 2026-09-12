..
   Licensed to the Apache Software Foundation (ASF) under one
   or more contributor license agreements.  See the NOTICE file
   distributed with this work for additional information
   regarding copyright ownership.  The ASF licenses this file
   to you under the Apache License, Version 2.0 (the
   "License"); you may not use this file except in compliance
   with the License.  You may obtain a copy of the License at

     http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing,
   software distributed under the License is distributed on an
   "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
   KIND, either express or implied.  See the License for the
   specific language governing permissions and limitations
   under the License.


=================
Human in the Loop
=================

.. _human-in-the-loop:

.. note::

    The person stays outside the graph. An action that needs them declares extra function
    parameters (runtime :ref:`inputs <inputref>`). You stop the application with
    ``run(halt_before=["human_step"])``, collect those values yourself, then call ``run``
    again and pass them as ``inputs``.

An agent can run on its own until it needs a person -- a prompt, a clarification, an
approval. Burr does not prompt the user. It stops, hands control back to your code, and
waits for the next ``run``.

The action that needs a person looks like any other action. The extra parameters are not
read from state; they come from the caller:

.. code-block:: python

    @action(reads=["draft"], writes=["approved"])
    def human_step(state: State, approved: bool) -> State:
        return state.update(approved=approved)

``approved`` is a runtime input. Bind long-lived objects (an API client, a DB handle) with
``.bind(...)``. Pass per-turn values with ``inputs={...}`` on ``run`` / ``step`` /
``iterate``. See :ref:`inputs <inputref>`.

----------------------------
``halt_before`` and ``run``
----------------------------

``Application.run`` walks the graph until a halt condition hits, then returns
``(action, result, state)``.

- ``halt_before=["human_step"]`` stops when ``human_step`` is the *next* action. That
  action has **not** run. ``result`` is ``None``. The returned ``action`` is
  ``human_step``.
- ``halt_after=["final_result"]`` stops after that action has run. ``result`` is that
  action's result dict. The returned ``action`` is ``final_result``.

If both could apply, ``halt_before`` wins. ``run`` always executes at least one action
before it checks halt conditions, then ``inputs`` apply only to that first action. Later
actions in the same ``run`` that also need ``inputs`` are undefined -- halt before those
instead, and pass their values on the next ``run``.

You can pass action names or tags (``"@tag:needs_human"``). The same halt arguments work
on ``iterate`` / ``arun`` / ``aiterate``. Details are in :ref:`Applications <applications>`.

--------------------------------
A graph with one handoff
--------------------------------

This is the shape ``run(halt_before=["human_step"])`` is for. No LLM required:

.. code-block:: python

    from burr.core import ApplicationBuilder, State, action

    @action(reads=[], writes=["task"])
    def start(state: State, task: str) -> State:
        return state.update(task=task)

    @action(reads=["task"], writes=["draft"])
    def agent_work(state: State) -> State:
        return state.update(draft=f"draft for: {state['task']}")

    @action(reads=["draft"], writes=["approved"])
    def human_step(state: State, approved: bool) -> State:
        return state.update(approved=approved)

    @action(reads=["draft", "approved"], writes=["result"])
    def finish(state: State) -> State:
        return state.update(result=state["draft"] if state["approved"] else None)

    app = (
        ApplicationBuilder()
        .with_actions(start, agent_work, human_step, finish)
        .with_transitions(
            ("start", "agent_work"),
            ("agent_work", "human_step"),
            ("human_step", "finish"),
        )
        .with_entrypoint("start")
        .build()
    )

    action, result, state = app.run(
        halt_before=["human_step"],
        inputs={"task": "write a thank-you note"},
    )
    # action.name == "human_step", result is None
    # start and agent_work have run; human_step has not
    # state["draft"] is ready for the person to look at

    action, result, state = app.run(
        halt_after=["finish"],
        inputs={"approved": True},
    )
    # first action of this run is human_step, so it receives approved=True
    # then finish runs; action.name == "finish"

The first ``run`` stops *before* ``human_step``. The second ``run`` starts *at*
``human_step``, so ``inputs={"approved": True}`` is what that action receives.

``app.get_next_action()`` tells you which action is queued if you want to inspect
without running.

---------------------------
A chat loop
---------------------------

When the human action is both the entrypoint and the place you return to, collect the
prompt in the outer loop and halt before that same action. The first step of each
``run`` is the human action (it gets ``inputs``); the application then continues until
that action is next again:

.. code-block:: python

    from burr.core import ApplicationBuilder, State, action

    @action(reads=[], writes=["prompt", "chat_history"])
    def human_input(state: State, prompt: str) -> State:
        return state.update(prompt=prompt).append(
            chat_history={"role": "user", "content": prompt}
        )

    @action(reads=["chat_history"], writes=["response", "chat_history"])
    def ai_response(state: State) -> State:
        reply = f"you said: {state['chat_history'][-1]['content']}"
        return state.update(response=reply).append(
            chat_history={"role": "assistant", "content": reply}
        )

    app = (
        ApplicationBuilder()
        .with_actions(human_input, ai_response)
        .with_transitions(
            ("human_input", "ai_response"),
            ("ai_response", "human_input"),
        )
        .with_state(chat_history=[])
        .with_entrypoint("human_input")
        .build()
    )

    while True:
        prompt = input("you: ")
        if prompt == "exit":
            break
        action, result, state = app.run(
            halt_before=["human_input"],
            inputs={"prompt": prompt},
        )
        print("ai:", state["response"])

In this two-node cycle, ``halt_after=["ai_response"]`` stops at the same place -- after
the model has spoken, before the next human turn. ``halt_before=["human_input"]`` is the
same stop, with ``result is None`` and ``action.name == "human_input"``. The getting
started chatbot uses ``halt_after=["ai_response"]`` for a single turn; a running CLI
example of the ``halt_before`` loop is
`examples/conversational-rag/graph_db_example/application.py <https://github.com/apache/burr/blob/main/examples/conversational-rag/graph_db_example/application.py>`_
(``human_converse`` / ``user_question``).

--------------------------------------
Several handoff points
--------------------------------------

Some applications need a person more than once, at different actions. Halt before every
action that needs ``inputs``, halt after the terminal action, and use ``action.name`` to
decide what to collect next.

This is the email assistant
(`examples/email-assistant <https://github.com/apache/burr/tree/main/examples/email-assistant>`_).
``process_input`` takes ``email_to_respond`` and ``response_instructions``.
``clarify_instructions`` takes ``clarification_inputs`` (a ``list[str]``).
``process_feedback`` takes ``feedback``. The graph goes
``process_input → determine_clarifications → (clarify_instructions?) → formulate_draft → process_feedback → … → final_result``.

.. code-block:: python

    inputs = {
        "email_to_respond": incoming,
        "response_instructions": instructions,
    }
    while True:
        action, result, state = app.run(
            halt_before=["clarify_instructions", "process_feedback"],
            halt_after=["final_result"],
            inputs=inputs,
        )
        if action.name == "clarify_instructions":
            # clarify_instructions has not run; questions are already in state
            answers = [input(q + " ") for q in state["clarification_questions"]]
            inputs = {"clarification_inputs": answers}
        elif action.name == "process_feedback":
            comment = input("feedback (empty accepts the draft): ")
            inputs = {"feedback": comment}
        elif action.name == "final_result":
            break

Include ``halt_after=["final_result"]``. Without it, an empty ``feedback`` sends the
graph through ``final_result`` and then leaves it with no next action, which ``run``
treats as undefined (it logs a warning).

The FastAPI wiring for the same halt list is
`examples/email-assistant/server.py <https://github.com/apache/burr/blob/main/examples/email-assistant/server.py>`_
(``_run_through``) and the walkthrough in
`examples/web-server <https://github.com/apache/burr/tree/main/examples/web-server>`_.

-----------------------------
Web servers and persistence
-----------------------------

The loop does not have to live in one process. On a web server each request loads the
application, calls ``run`` once, and returns. The next request supplies the next
``inputs``.

``examples/email-assistant`` does that with ``initialize_from(..., resume_at_next_action=True)``
and a persister / tracker keyed by ``app_id``. The person can come back seconds or days
later. See :ref:`State Persistence <state-persistence>`.

``app.get_next_action()`` is useful here: the handler can tell the client which form to
show without advancing the graph.

-----------------
Command-line only
-----------------

If the application only ever runs in a terminal, you can call ``input(...)`` inside an
action and skip the outer loop. That does not work for a web server, a persisted app, or
any caller that is not sitting on stdin. Prefer ``halt_before`` + ``inputs`` unless you
are writing a one-off CLI.

---------------------------
Nested applications
---------------------------

Halting *inside* a sub-application and surfacing that to the parent is more involved.
The wrapping action runs the child with ``halt_before``, then either:

- sets a flag such as ``need_input=True`` and returns, with a parent transition back to
  itself, or
- copies the child's finished state up and continues.

The parent still collects the person's values and passes them as ``inputs`` into the
wrapping action on the next ``run``. The child is not visible to the parent's
``halt_before`` list.

------------
See also
------------

- :ref:`Applications <applications>` -- ``run``, ``iterate``, ``halt_before`` / ``halt_after``
- :ref:`inputs <inputref>` -- runtime inputs vs ``.bind(...)``
- :ref:`State Persistence <state-persistence>` -- pause and resume across requests
- `Email assistant <https://github.com/apache/burr/tree/main/examples/email-assistant>`_
- `Graph-DB RAG CLI loop <https://github.com/apache/burr/blob/main/examples/conversational-rag/graph_db_example/application.py>`_
- `Burr in a web server <https://github.com/apache/burr/tree/main/examples/web-server>`_
