# Testing NDJSON Log Splitting for Thinking and Output

This document outlines how to test the new feature that splits a model's "thinking" process and its actual output into separate entries in the NDJSON log when using `--logndjson`.

## Feature Overview
When a model provides reasoning via the `msg.thinking` field (common in models like DeepSeek-R1 or LFM thinking models), the engine should now produce two distinct JSON lines in the NDJSON log:
1. A line with `"mode": "thinking"` containing the thought content.
2. A line with `"mode": "output"` containing the actual response content.

If no thinking is provided, a single standard assistant message is logged as before.

## Test Scenarios

### 1. Split Thinking and Output (The Primary Case)
**Setup:** Mock the Ollama client to return a stream where one chunk contains `thinking` text and subsequent chunks contain `content` text.
**Expected Result:** The NDJSON log file should contain exactly two assistant messages:
- One with `"mode": "thinking"` and the correct thought content.
- One with `"mode": "output"` and the correct response content.

### 2. Standard Output (No Thinking)
**Setup:** Mock the Ollama client to return a stream containing only `content` text, without any `thinking` field.
**Expected Result:** The NDJSON log file should contain exactly one assistant message with no `"mode"` key (or standard format), representing the full response.

### 3. Empty Thinking/Content Edge Cases
**Setup:** Mock chunks where `thinking` is an empty string or `content` is None.
**Expected Result:** Ensure the logger handles these gracefully without producing malformed JSON or extra empty lines that break parsers.

## Implementation Guide for Tests

We recommend using the `unittest` module along with `unittest.mock` to simulate the Ollama stream and capture log output.

### Mocking Strategy
Since `run_with_tools` is a long-running loop, you should mock:
1. **The Client:** Use `MagicMock` for the `client` object. Its `.chat()` method should return an iterator of objects that mimic the Ollama response chunks (having `.content`, `.thinking`, and `.tool_calls` attributes).
2. **Log Output:** Instead of writing to a real file, pass an `io.StringIO` object as the `ndjson_log_file_handle`. This allows you to easily inspect the captured string.

### Example Test Structure

```python
import unittest
import json
import io
from unittest.mock import MagicMock
from tool_base.engine import run_with_tools

class MockChunk:
    """Mocks an Ollama response chunk."""
    def __init__(self, content=None, thinking=None, tool_calls=None):
        self.content = content or ""
        self.thinking = thinking or ""
        self.tool_calls = tool_calls or []

class TestNDJSONLogging(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        # Setup common parameters for run_with_tools to avoid errors
        self.params = {
            "client": self.client,
            "model": "test-model",
            "messages": [{"role": "user", "content": "Hello"}],
            "loaded_tools": [],
            "ollama_tools": None,
            "options": {},
            "keep_alive": True,
            "show_thinking": False,
            "no_safety_system_prompt": True,
            "ndjson_log_file_handle": io.StringIO(),
        }

    def test_split_thinking_and_output(self):
        # 1. Prepare Mock Stream: Chunk 1 (Thinking) -> Chunk 2 (Content)
        stream = [
            MockChunk(thinking="I am thinking about this."),
            MockChunk(content="The answer is 42.")
        ]
        self.client.chat.return_value = iter(stream)

        # 2. Execute
        run_with_tools(**self.params)

        # 3. Verify Logs
        log_output = self.params["ndjson_log_file_handle"].getvalue().strip()
        lines = log_output.split('\n')
        
        # We expect at least two lines (one for thinking, one for output)
        # Note: Depending on implementation, there might be more if system prompt is logged
        # but we are looking for the assistant messages specifically.
        assistant_msgs = []
        for line in lines:
            try:
                data = json.loads(line)
                if data["message"].get("role") == "assistant":
                    assistant_msgs.append(data["message"])
            except (json.JSONDecodeError, KeyError):
                continue

        self.assertEqual(len(assistant_msgs), 2)
        
        # Check Thinking Message
        self.assertEqual(assistant_msgs[0]["mode"], "thinking")
        self.assertEqual(assistant_msgs[0]["content"], "I am thinking about this.")
        
        # Check Output Message
        self.assertEqual(assistant_msgs[1]["mode"], "output")
        self.assertEqual(assistant_msgs[1]["content"], "The answer is 42.")

    def test_no_thinking_logs_single_message(self):
        # 1. Prepare Mock Stream: Only Content
        stream = [MockChunk(content="Just a normal response.")]
        self.client.chat.return_value = iter(stream)

        # 2. Execute
        run_with_tools(**self.params)

        # 3. Verify Logs
        log_output = self.params["ndjson_log_file_handle"].getvalue().strip()
        lines = log_output.split('\n')
        
        assistant_msgs = []
        for line in lines:
            try:
                data = json.loads(line)
                if data["message"].get("role") == "assistant":
                    assistant_msgs.append(data["message"])
            except (json.JSONDecodeError, KeyError):
                continue

        self.assertEqual(len(assistant_msgs), 1)
        self.assertNotIn("mode", assistant_msgs[0])
        self.assertEqual(assistant_msgs[0]["content"], "Just a normal response.")

if __name__ == "__main__":
    unittest.main()
```
