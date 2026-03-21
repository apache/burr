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

import collections
import dataclasses
import inspect
import logging
import pathlib
from typing import Any, Callable, List, Literal, Optional, Set, Tuple, Union

from burr.core.action import Action, Condition, create_action, default
from burr.core.state import State
from burr.core.validation import BASE_ERROR_MESSAGE, assert_set

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class Transition:
    """Internal, utility class"""

    from_: Action
    to: Action
    condition: Condition


def _validate_actions(actions: Optional[List[Action]]):
    assert_set(actions, "_actions", "with_actions")
    if len(actions) == 0:
        raise ValueError("Must have at least one action in the application!")
    seen_action_names = set()
    for action in actions:
        if action.name in seen_action_names:
            raise ValueError(
                f"Action: {action.name} is duplicated in the actions list. "
                "actions have unique names. This could happen "
                "if you add two actions with the same name or add a graph that "
                "has actions with the same name as any that already exist."
            )
        seen_action_names.add(action.name)


def _validate_transitions(
    transitions: Optional[List[Tuple[str, str, Condition]]], actions: Set[str]
):
    exhausted = {}  # items for which we have seen a default transition
    for from_, to, condition in transitions:
        if from_ not in actions:
            raise ValueError(
                f"Transition source: `{from_}` not found in actions! "
                f"Please add to actions using with_actions({from_}=...)"
            )
        if to not in actions:
            raise ValueError(
                f"Transition target: `{to}` not found in actions! "
                f"Please add to actions using with_actions({to}=...)"
            )
        if condition.name == "default":  # we have seen a default transition
            if from_ in exhausted:
                raise ValueError(
                    f"Transition `{from_}` -> `{to}` is redundant -- "
                    f"a default transition has already been set for `{from_}`"
                )
            exhausted[from_] = True
    return True


def _render_graphviz(
    graphviz_obj,
    output_file_path: Union[str, pathlib.Path],
    view: bool = False,
    write_dot: bool = False,
) -> None:
    """Generate an image file for the graphviz object.

    Use graphviz's `.render()` to produce a dot file or open the image
    on the OS (i.e., `view` arg)
    Use .pipe()` to not produce a not file; can't open the image
    """
    output_file_path = pathlib.Path(output_file_path)

    if output_file_path.suffix != "":
        # infer format from path; i.e., extract `svg` from the `.svg` suffix
        format = output_file_path.suffix.partition(".")[-1]
    else:
        format = "png"

    path_without_suffix = pathlib.Path(output_file_path.parent, output_file_path.stem)
    if write_dot or view:
        # `.render()` appends the `format` kwarg to the filename
        # i.e., we need to pass `/my/filepath` to generate `/my/filepath.png`
        # otherwise, passing `/my/filepath.png` will generate `/my/filepath.png.png`
        graphviz_obj.render(path_without_suffix, format=format, view=view)
    else:
        # `.pipe()` doesn't append the format to the filename, so we do it explicitly
        pathlib.Path(f"{path_without_suffix}.{format}").write_bytes(
            graphviz_obj.pipe(format=format)
        )


@dataclasses.dataclass
class Graph:
    """Graph class allows you to specify actions and transitions between them.
    You will never instantiate this directly, just through the GraphBuilder,
    or indirectly through the ApplicationBuilder."""

    actions: List[Action]
    transitions: List[Transition]

    def __post_init__(self):
        """Sets up initial state for easy graph operations later"""
        self._action_map = {action.name: action for action in self.actions}
        self._adjacency_map = self._create_adjacency_map(self.transitions)
        self._action_tag_map = self._create_action_tag_map(self.actions)

    @staticmethod
    def _create_adjacency_map(transitions: List[Transition]) -> dict:
        adjacency_map = collections.defaultdict(list)
        for transition in transitions:
            from_ = transition.from_
            to = transition.to
            adjacency_map[from_.name].append((to.name, transition.condition))
        return adjacency_map

    @staticmethod
    def _create_action_tag_map(actions: List[Action]) -> dict[str, List[Action]]:
        """Creates a mapping of action tags to lists of corresponding actions.

        :param actions: List of Action objects
        :return: Dictionary mapping action tags to lists of matching Action objects
        """
        tag_map = collections.defaultdict(list)
        for action in actions:
            for tag in action.tags:
                tag_map[tag].append(action)
        return dict(tag_map)

    def get_next_node(
        self, prior_step: Optional[str], state: State, entrypoint: str
    ) -> Optional[Action]:
        """Gives the next node to execute given state + prior step."""
        if prior_step is None:
            return self._action_map[entrypoint]
        possibilities = self._adjacency_map[prior_step]
        for next_action, condition in possibilities:
            if condition.run(state)[Condition.KEY]:
                return self._action_map[next_action]
        return None

    def get_action(self, action_name: str) -> Optional[Action]:
        """Gets an action object given the action name"""
        if action_name not in self._action_map:
            raise ValueError(
                BASE_ERROR_MESSAGE + f"Action: {action_name} not found in graph. "
                f"Actions are: {self._action_map.keys()}"
            )
        return self._action_map.get(action_name)

    def get_actions_by_tag(self, tag: str) -> List[Action]:
        """Gets a list of actions given a tag. Note that, if no tags match the action a ValueError will be raised."""
        if tag not in self._action_tag_map:
            raise ValueError(
                BASE_ERROR_MESSAGE + f"Tag: {tag} not found in graph. "
                f"Tags are: {self._action_tag_map.keys()}."
            )
        return self._action_tag_map.get(tag)

    def visualize(
        self,
        output_file_path: Optional[Union[str, pathlib.Path]] = None,
        include_conditions: bool = False,
        include_state: bool = False,
        view: bool = False,
        engine: Literal["graphviz"] = "graphviz",
        write_dot: bool = False,
        **engine_kwargs: Any,
    ) -> Optional["graphviz.Digraph"]:  # noqa: F821
        """Visualizes the graph using graphviz. This will render the graph.

        :param output_file_path: The path to save this to, None if you don't want to save. Do not pass an extension
            for graphviz, instead pass `format` in `engine_kwargs` (e.g. `format="png"`)
        :param include_conditions: Whether to include condition strings on the edges (this can get noisy)
        :param include_state: Whether to indicate the action "signature" (reads/writes) on the nodes
        :param view: Whether to bring up a view
        :param engine: The engine to use -- only graphviz is supported for now
        :param write_dot: If True, produce a graphviz dot file
        :param engine_kwargs: Additional kwargs to pass to the engine
        :return: The graphviz object
        """
        if engine != "graphviz":
            raise ValueError(f"Only graphviz is supported for now, not {engine}")
        try:
            import graphviz  # noqa: F401
        except ModuleNotFoundError:
            logger.exception(
                " graphviz is required for visualizing the application graph. Install it with:"
                '\n\n  pip install "burr[graphviz]" or pip install graphviz \n\n'
            )
            return
        digraph_attr = dict(
            graph_attr=dict(
                rankdir="TB",
                ranksep="0.4",
                compound="false",
                concentrate="false",
            ),
            node_attr=dict(
                fontname="Helvetica",
                margin="0.15",
                fillcolor="#b4d8e4",
            ),
        )
        for g_key, g_value in engine_kwargs.items():
            if isinstance(g_value, dict):
                digraph_attr[g_key].update(**g_value)
            else:
                digraph_attr[g_key] = g_value
        digraph = graphviz.Digraph(**digraph_attr)
        for action in self.actions:
            label = (
                action.name
                if not include_state
                else f"{action.name}({', '.join(action.reads)}): {', '.join(action.writes)}"
            )
            digraph.node(action.name, label=label, shape="box", style="rounded,filled")
            required_inputs, optional_inputs = action.optional_and_required_inputs
            for input_ in required_inputs | optional_inputs:
                if input_.startswith("__"):
                    # These are internally injected by the framework
                    continue
                input_name = f"input__{input_}"
                digraph.node(input_name, shape="rect", style="dashed", label=f"input: {input_}")
                digraph.edge(input_name, action.name)
        for transition in self.transitions:
            condition = transition.condition
            digraph.edge(
                transition.from_.name,
                transition.to.name,
                label=condition.name if include_conditions and condition is not default else None,
                style="dashed" if transition.condition is not default else "solid",
            )

        if output_file_path:
            _render_graphviz(
                graphviz_obj=digraph,
                output_file_path=output_file_path,
                view=view,
                write_dot=write_dot,
            )

        return digraph

    def _repr_mimebundle_(self, include=None, exclude=None, **kwargs):
        """Attribute read by notebook renderers
        This returns the attribute of the `graphviz.Digraph` returned by `self.display_all_functions()`

        The parameters `include`, `exclude`, and `**kwargs` are required, but not explicitly used
        ref: https://ipython.readthedocs.io/en/stable/config/integrating.html
        """
        dot = self.visualize(include_conditions=True, include_state=False)
        return dot._repr_mimebundle_(include=include, exclude=exclude, **kwargs)


class GraphBuilder:
    """GraphBuilder class. This allows you to construct a graph without considering application concerns.
    While you can (and at first, should) use the ApplicationBuidler (which has the same API), this is lower level
    and allows you to decouple concerns, reuse the same graph object, etc..."""

    def __init__(self):
        """Initializes the graph builder."""
        self.transitions: Optional[List[Tuple[str, str, Condition]]] = []
        self.actions: Optional[List[Action]] = None

    def with_actions(
        self, *action_list: Union[Action, Callable], **action_dict: Union[Action, Callable]
    ) -> "GraphBuilder":
        """Adds an action to the application. The actions are granted names (using the with_name)
        method post-adding, using the kw argument. If it already has a name (or you wish to use the function name, raw, and
        it is a function-based-action), then you can use the *args* parameter. This is the only supported way to add actions.

        :param action_list: Actions to add -- these must have a name or be function-based (in which case we will use the function-name)
        :param action_dict: Actions to add, keyed by name
        :return: The application builder for future chaining.
        """
        if self.actions is None:
            self.actions = []
        for action_value in action_list:
            if inspect.isfunction(action_value):
                self.actions.append(create_action(action_value, action_value.__name__))
            elif isinstance(action_value, Action):
                if not action_value.name:
                    raise ValueError(
                        BASE_ERROR_MESSAGE + f"Action: {action_value} must have a name set. "
                        "If you hit this, you should probably be using the "
                        "**kwargs parameter (or call with_name(your_name) on the action)."
                    )
                self.actions.append(action_value)
        for key, value in action_dict.items():
            self.actions.append(create_action(value, key))
        return self

    def with_transitions(
        self,
        *transitions: Union[
            Tuple[Union[str, list[str]], str], Tuple[Union[str, list[str]], str, Condition]
        ],
    ) -> "GraphBuilder":
        """Adds transitions to the graph. Transitions are specified as tuples of either:
            1. (from, to, condition)
            2. (from, to)  -- condition is set to DEFAULT (which is a fallback)

        Transitions will be evaluated in order of specification -- if one is met, the others will not be evaluated.
        Note that one transition can be terminal -- the system doesn't have


        :param transitions: Transitions to add
        :return: The application builder for future chaining.
        """
        for transition in transitions:
            from_, to_, *conditions = transition
            if len(conditions) > 0:
                condition = conditions[0]
            else:
                condition = default
            if not isinstance(from_, list):
                from_ = [from_]
            for action in from_:
                if not isinstance(action, str):
                    raise ValueError(f"Transition source must be a string, not {action}")
                if not isinstance(to_, str):
                    raise ValueError(f"Transition target must be a string, not {to_}")
                self.transitions.append((action, to_, condition))
        return self

    def with_graph(self, graph: Graph) -> "GraphBuilder":
        """Adds an existing graph to the builder. Note that if you have any name clashes
        this will error out. This would happen if you add actions with the same name as actions
        that already exist.

        :param graph: The graph to add
        :return: The application builder for future chaining.
        """
        if self.actions is None:
            self.actions = []
        if self.transitions is None:
            self.transitions = []
        self.actions.extend(graph.actions)
        self.transitions.extend(
            (transition.from_.name, transition.to.name, transition.condition)
            for transition in graph.transitions
        )
        return self

    def build(self) -> Graph:
        """Builds/finalizes the graph.

        :return: The graph object
        """
        _validate_actions(self.actions)
        actions_by_name = {action.name: action for action in self.actions}
        all_actions = set(actions_by_name.keys())
        _validate_transitions(self.transitions, all_actions)
        return Graph(
            actions=self.actions,
            transitions=[
                Transition(
                    from_=actions_by_name[from_],
                    to=actions_by_name[to],
                    condition=condition,
                )
                for from_, to, condition in self.transitions
            ],
        )
