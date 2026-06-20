# Contribution: Union Type Support for Streaming Actions

## Project Information
- **Project:** Apache Burr (incubating)
- **Issue:** Support Union Types in `@streaming_action.pydantic()` decorator
- **Working Branch:** `fix-union-stream-types` (in your fork)
- **Status:** Phase II - Reproduction & Planning Complete

---

## Reproduction Process

### Environment Setup

#### Prerequisites
- Python 3.9+ (tested on 3.11)
- Git
- pip or conda for package management

#### Setup Steps

1. **Clone your fork:**
   ```bash
   git clone https://github.com/<your-username>/burr.git
   cd burr
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/Scripts/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install project in development mode:**
   ```bash
   pip install -e ".[pydantic]"
   ```
   Note: The `[pydantic]` extra ensures Pydantic is installed for testing.

4. **Verify installation:**
   ```bash
   python -c "import burr; print(burr.__version__)"
   ```

#### Environment Notes
- No environment variables required for reproducing this issue
- All dependencies are listed in `pyproject.toml`
- The Pydantic integration is optional but required for this feature

### Steps to Reproduce

#### Step 1: Create Test Models
Create a test file `test_union_repro.py`:

```python
from pydantic import BaseModel
from typing import Generator, Optional, Tuple, Union
from burr.core import State
from burr.core.action import streaming_action

# Define Pydantic models for streaming results
class TextChunk(BaseModel):
    """Represents a text chunk from the stream."""
    text: str
    chunk_id: int

class StructuredResult(BaseModel):
    """Represents a structured result."""
    summary: str
    confidence: float

class InputState(BaseModel):
    """Input state."""
    prompt: str

class OutputState(BaseModel):
    """Output state."""
    response: str
```

#### Step 2: Attempt Union Type with Pipe Operator (Python 3.10+)
Add this to your test file:

```python
# This will cause a type error before the fix
@streaming_action.pydantic(
    reads=["prompt"],
    writes=["response"],
    state_input_type=InputState,
    state_output_type=OutputState,
    stream_type=TextChunk | StructuredResult,  # Type error here
)
def stream_with_pipe_operator(state: State) -> Generator[Tuple[TextChunk | StructuredResult, Optional[OutputState]], None, None]:
    """Streaming action using union with pipe operator."""
    yield TextChunk(text="Hello", chunk_id=1), None
    yield StructuredResult(summary="Done", confidence=0.95), OutputState(response="Complete")
```

#### Step 3: Attempt Union Type with typing.Union
Add this to your test file:

```python
# This will also cause a type error before the fix
@streaming_action.pydantic(
    reads=["prompt"],
    writes=["response"],
    state_input_type=InputState,
    state_output_type=OutputState,
    stream_type=Union[TextChunk, StructuredResult],  # Type error here
)
def stream_with_typing_union(state: State) -> Generator[Tuple[Union[TextChunk, StructuredResult], Optional[OutputState]], None, None]:
    """Streaming action using Union from typing."""
    yield TextChunk(text="Hi", chunk_id=1), None
    yield StructuredResult(summary="Finished", confidence=0.90), OutputState(response="Done")
```

#### Step 4: Run Type Checker
```bash
# Using mypy (if installed)
mypy test_union_repro.py

# Or using Pylance through your IDE
# In VS Code: Check the "Problems" panel for type errors
```

#### Step 5: Observe the Error
**Before the fix**, you will see errors like:
```
error: Argument "stream_type" to "pydantic" of "streaming_action" has incompatible type "Union[type[TextChunk], type[StructuredResult]]"; expected "Union[type[BaseModel], type[dict]]"
```

### Expected Behavior (After Fix)
After the fix is applied:
1. No type errors in your IDE or from mypy
2. The decorators accept the union types without complaint
3. Runtime behavior is unchanged (union types flow through correctly)

### Reproduction Evidence

**Your working branch:** `https://github.com/<your-username>/burr/tree/fix-union-stream-types`

**Test reproduction file:** Created at workspace root as reference (will be cleaned up before PR)

---

## Root Cause Analysis

### Problem Location
The issue is in the type annotations for the `stream_type` parameter across two files:

1. **`burr/core/action.py` (line ~1510)**
   - In the `streaming_action.pydantic()` method
   - Current type: `Union[Type["BaseModel"], Type[dict]]`

2. **`burr/integrations/pydantic.py` (line ~272)**
   - In the `PartialType` type alias definition
   - Current type: `Union[Type[pydantic.BaseModel], Type[dict]]`

### Why Union Types Are Rejected
- Union types created with `|` (Python 3.10+) are `types.UnionType` objects
- Union types from `typing.Union` are `typing._UnionGenericAlias` objects  
- Neither of these types match `Union[Type[BaseModel], Type[dict]]`
- Type checkers (mypy, Pylance, etc.) reject these values as incompatible

### Runtime vs. Type-Checking
- At **runtime**, the union type value flows through without validation — it actually works!
- At **type-checking time**, the IDE and mypy reject the code as invalid
- This creates a false positive: code that would work is flagged as an error

### Key Functions Involved
```
streaming_action.pydantic() 
  ↓
pydantic_streaming_action() 
  ↓
_validate_and_extract_signature_types_streaming() 
  ↓
intermediate_result_type (stored in action schema)
```

The union type flows through all of these unchanged, so no runtime changes are needed.

---

## Solution Approach

### Understanding the Problem
The type system is too restrictive for the `stream_type` parameter. It only accepts a single type, but users want to specify that an action can stream multiple different types (Model1 or Model2). The union type syntax (`|` or `typing.Union`) is the natural Python way to express this, but the current type annotation rejects it.

### Matching Similar Solutions
This pattern exists elsewhere in Python typing:
- Function return types can be unions: `def foo() -> Model1 | Model2:`
- Variable types can be unions: `result: Model1 | Model2 = ...`
- The type system needs to accept union types as valid values

### Implementation Plan

#### Changes Required

**File 1: `burr/integrations/pydantic.py` (line ~272)**
- Change `PartialType = Union[Type[pydantic.BaseModel], Type[dict]]`
- To: `PartialType = Union[Type[pydantic.BaseModel], Type[dict], object]`
- Add explanatory comment about union type support
- Rationale: `object` is the base type in Python's type system and represents any runtime type

**File 2: `burr/integrations/pydantic.py` (line ~303-310)**
- Update `_validate_and_extract_signature_types_streaming()` function signature
- Change parameter type from explicit Union to `PartialType`
- Change return type from explicit Union to `PartialType`
- No runtime logic changes needed

**File 3: `burr/core/action.py` (line ~1510)**
- Update `stream_type` parameter in `streaming_action.pydantic()` 
- Change from `Union[Type["BaseModel"], Type[dict]]` to `Union[Type["BaseModel"], Type[dict], object]`
- Update docstring to mention union type support
- Add example showing usage with `|` operator

### Why This Approach Works
- Minimal change: only type annotations, no runtime logic changes
- Backward compatible: all existing code continues to work
- Works across Python versions: `object` is available in Python 3.9+
- Type-safe: more specific than `Any`, clearer intent with proper comments
- Union types at runtime are type-compatible with `object` in the union

### Files to Modify
1. `burr/integrations/pydantic.py` (2 locations)
2. `burr/core/action.py` (1 location)

**Total: 3 targeted changes in 2 files**

---

## Verification Plan

### How to Test the Fix

#### Manual Testing
After applying the fix:
1. Run the reproduction script from "Steps to Reproduce" section
2. Verify no type errors appear in mypy or IDE
3. Verify the decorated functions can be created without runtime errors

#### Automated Testing
Create unit tests in `tests/integrations/test_pydantic_union_types.py`:

```python
def test_streaming_action_with_union_pipe_operator():
    """Test that union types with | operator are accepted."""
    @streaming_action.pydantic(
        reads=["input"],
        writes=["output"],
        state_input_type=InputState,
        state_output_type=OutputState,
        stream_type=Model1 | Model2,
    )
    def my_action(state: State):
        pass
    # Should not raise any errors

def test_streaming_action_with_typing_union():
    """Test that typing.Union types are accepted."""
    @streaming_action.pydantic(
        reads=["input"],
        writes=["output"],
        state_input_type=InputState,
        state_output_type=OutputState,
        stream_type=Union[Model1, Model2],
    )
    def my_action(state: State):
        pass
    # Should not raise any errors

def test_streaming_action_backward_compatibility():
    """Test that existing single-type patterns still work."""
    @streaming_action.pydantic(
        reads=["input"],
        writes=["output"],
        state_input_type=InputState,
        state_output_type=OutputState,
        stream_type=Model1,  # Single type should still work
    )
    def my_action(state: State):
        pass
    # Should not raise any errors
```

#### Verification Checklist
- [ ] Type checker (mypy) reports no errors on union type usage
- [ ] IDE/Pylance shows no squiggly lines under union types
- [ ] Existing single-type patterns continue to work (no regression)
- [ ] Unit tests for all union type syntaxes pass
- [ ] Backward compatibility tests pass
- [ ] No breaking changes to runtime behavior

### Self-Review Checklist
Before submitting your PR, verify:
- [ ] Changes match `CONTRIBUTING.md` guidelines (check project's contribution guidelines)
- [ ] Commit messages are clear and follow project conventions
- [ ] Code follows project's style guide (PEP 8 for Python)
- [ ] All tests pass: `pytest tests/integrations/`
- [ ] No new warnings from type checkers
- [ ] Documentation is updated (docstrings, comments)

---

## Key References

### Files in Scope
- `burr/core/action.py` — Where `streaming_action` decorator is defined
- `burr/integrations/pydantic.py` — Where `PartialType` and related functions are defined
- `tests/integrations/` — Where unit tests should be added

### Type System References
- Current implementation: [burr/core/action.py](burr/core/action.py) line 1503-1540
- Pydantic integration: [burr/integrations/pydantic.py](burr/integrations/pydantic.py) line 270-380
- Related test file: `tests/integrations/test_pydantic.py` (check existing patterns)

### Python Type Hints
- [PEP 604 - Union as Type Syntax (`|` operator)](https://www.python.org/dev/peps/pep-0604/)
- [typing.Union documentation](https://docs.python.org/3/library/typing.html#typing.Union)

---

## Phase II Status

✅ **Completed:**
1. Local development environment set up and verified
2. Issue reproduced with clear steps
3. Root cause identified and documented
4. Solution plan written with implementation details
5. Verification strategy defined
6. Changes scoped to 3 locations in 2 files

**Ready for:** Phase III - Implementation (write the actual code changes)

**Next Steps:**
1. Review this plan with mentors/maintainers for feedback
2. Implement the changes as outlined
3. Write and run tests
4. Submit pull request in Phase III

---

## Questions & Notes

### For Code Review
- Should we add runtime validation to ensure only valid types are passed?
- Is there existing discussion about union type support in the project?
- Any specific test coverage requirements for the Pydantic integration?

### Additional Context
- This is a type annotation only fix (no runtime logic changes)
- The fix maintains full backward compatibility
- Estimated effort: 2-4 hours including tests and documentation
