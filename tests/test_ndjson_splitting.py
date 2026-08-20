import unittest
import json
import io
from unittest.mock import MagicMock
from tool_base.engine import run_with_tools

class MockChunk:
    """Mocks an Ollama response chunk."""
    def __init__(self, content=None, thinking=None, tool_calls=None):
        from unittest.mock import MagicMock
        self.message = MagicMock()
        self.message.content = content or ""
        self.message.thinking = thinking or ""
        self.message.tool_calls = tool_calls or []

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
        assistant_msgs = []
        for line in lines:
            try:
                data = json.loads(line)
                if data["message"].get("role") == "assistant":
                    assistant_msgs.append(data["message"])
            except (json.JSONDecodeError, KeyError):
                continue

        self.assertEqual(len(assistant_msgs), 2, f"Expected 2 assistant messages, got {len(assistant_msgs)}")
        
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
