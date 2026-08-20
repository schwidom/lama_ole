# Issue: Missing Thought Data in NDJSON Logs

## Description
The `--logndjson` option is intended to provide a newline-delimited JSON log of all conversation messages (user, assistant, and tool) for auditing or training purposes. 

However, currently, the `run_with_tools` loop in `tool_base/engine.py` handles model "thinking" chunks (the `msg.thinking` field from Ollama's streaming API) separately from the main content stream. While these thinking chunks are correctly written to a dedicated thought log file (if `--thoughtlog` is provided), they are **not** added to the conversation history (`messages`) or included in the assistant messages that are logged via `ndjson_log_file_handle`.

## Root Cause
In `tool_base/engine.py`, the `run_with_tools` function iterates over the model's response stream:
1. When a chunk contains `thinking` content, it is written to the `thought_logger` but not appended to any local buffer that contributes to the final assistant message.
2. The `response_content` variable only accumulates `msg.content`.
3. Consequently, when an `assistant_msg` is constructed and logged to NDJSON (either because tool calls were detected or the stream ended), it only contains the text from `msg.content`, completely omitting the reasoning/thinking process that preceded it.

## Impact
Users attempting to reconstruct conversation flows from `--logndjson` files will find that the "reasoning" steps of the model are missing, making it impossible to see why a model decided to call a specific tool or arrived at a particular conclusion.
