# 001: Overview — Class-Based RunConfig Parameter Refactoring

## 1. Problem Statement

In `lama_ole`, the main conversation state is managed by the `ChatState` dataclass (`chat.py`). When executing a model interaction turn, `ChatState` delegates execution to the core engine function `run_with_tools()` (`tool_base/engine.py`).

Over time, as new features were added to the CLI and engine, parameters were added simultaneously to both `ChatState` and `run_with_tools()`.

This has resulted in severe parameter fragmentation and duplication:
1. **Massive Signature Duplication:** `run_with_tools()` takes 27 distinct parameters, 25 of which map 1:1 directly to fields on `ChatState`.
2. **Boilerplate Callsites:** Calling `run_with_tools()` requires ~30 lines of explicit keyword unpacking from `state`.
3. **The `mode_state` Anomaly:** To support dynamic mid-turn state queries, the engine accepts `mode_state` (which is the `ChatState` instance itself) alongside 25 individual properties extracted from `state`.
4. **Maintenance Fragility:** Adding or modifying an execution setting requires modifying `ChatState`, `run_with_tools()` signature, and multiple callsites.

---

## 2. Refactoring Vision: The `RunConfig` Class

To address this complexity cleanly and eliminate boilerplate, this refactoring introduces a dedicated configuration class, **`RunConfig`**, that encapsulates all static execution parameters.

### Core Architectural Decisions:
- **Dedicated Configuration Object:** Create a typed `RunConfig` dataclass in `tool_base/config.py` to hold execution settings.
- **Strict Configuration Passing:** Refactor `run_with_tools()` to strictly accept configuration parameters via a `RunConfig` object. No keyword overrides or parameter unpacking will be supported.
- **State Composition:** `ChatState` will compose `RunConfig` as `state.config`.
- **Full Field Refactoring:** Fully refactor the codebase to replace direct attribute access on `ChatState` (e.g., `state.model`) with structured access (e.g., `state.config.model`).
- **Callsite Simplification:** Streamline callsites to pass only the active message history, loaded tools, and the consolidated `RunConfig` object.

---

## 3. Structure of the Refactoring Blueprint

This blueprint directory (`./llm_blueprint/2026_09_24_18_ChatState_run_with_tools_refactoring/`) contains the following detailed plans:

- **`001_overview.md`**: Problem statement, core architectural decisions, and blueprint index (this document).
- **`002_runconfig_class_definition.md`**: Complete specification of the new `RunConfig` dataclass and its attributes.
- **`003_run_with_tools_signature_and_logic.md`**: Refactored signature of `run_with_tools()` and its internal logic.
- **`004_codebase_and_callsite_migration.md`**: Comprehensive migration plan for `chat.py`, `lama_ole.py`, and the test suite under the full field refactoring constraint.
- **`005_implementation_plan.md`**: Step-by-step phased execution roadmap with validation checkpoints.
