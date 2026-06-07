#!/usr/bin/env python3
"""Protocol tests for the Sprout Debug Adapter."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("sprout_dap_test", ROOT / "tools" / "sprout_dap.py")
assert SPEC and SPEC.loader
DAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DAP)


def decode_messages(raw: bytes) -> list[dict]:
    messages = []
    offset = 0
    while offset < len(raw):
        boundary = raw.index(b"\r\n\r\n", offset)
        headers = raw[offset:boundary].decode("ascii")
        length = int(next(line.split(":", 1)[1] for line in headers.splitlines() if line.lower().startswith("content-length:")))
        start = boundary + 4
        messages.append(json.loads(raw[start:start + length].decode("utf-8")))
        offset = start + length
    return messages


def request(adapter, seq: int, command: str, arguments: dict | None = None) -> dict:
    before = len(adapter.writer.getvalue())
    adapter.handle({"seq": seq, "type": "request", "command": command, "arguments": arguments or {}})
    messages = decode_messages(adapter.writer.getvalue()[before:])
    return next(message for message in messages if message.get("type") == "response")


def wait_for_event(adapter, name: str, start: int = 0, timeout: float = 2.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        messages = decode_messages(adapter.writer.getvalue())
        matches = [message for message in messages[start:] if message.get("type") == "event" and message.get("event") == name]
        if matches:
            return matches[-1]
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {name}")


def test_breakpoint_stack_variables_and_continue() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        program = Path(tmp) / "main.sprout"
        program.write_text("def add(score):\n  score = score + 2\n  say score\n\nadd(1)\n", encoding="utf-8")
        adapter = DAP.SproutDebugAdapter(reader=io.BytesIO(), writer=io.BytesIO())

        initialized = request(adapter, 1, "initialize")
        assert initialized["success"]
        assert initialized["body"]["supportsConfigurationDoneRequest"]

        launched = request(adapter, 2, "launch", {"program": str(program), "args": ["demo"]})
        assert launched["success"]

        breakpoints = request(adapter, 3, "setBreakpoints", {
            "source": {"path": str(program)},
            "breakpoints": [{"line": 2}],
        })
        assert breakpoints["body"]["breakpoints"][0]["verified"] is True

        before_start = len(decode_messages(adapter.writer.getvalue()))
        request(adapter, 4, "configurationDone")
        stopped = wait_for_event(adapter, "stopped", before_start)
        assert stopped["body"]["reason"] == "breakpoint"

        stack = request(adapter, 5, "stackTrace", {"threadId": 1})
        assert stack["body"]["stackFrames"][0]["line"] == 2
        assert stack["body"]["stackFrames"][0]["name"] == "add(score)"
        frame_id = stack["body"]["stackFrames"][0]["id"]

        scopes = request(adapter, 6, "scopes", {"frameId": frame_id})
        assert scopes["body"]["scopes"][0]["name"] == "Locals - add(score)"
        locals_ref = scopes["body"]["scopes"][0]["variablesReference"]
        variables = request(adapter, 7, "variables", {"variablesReference": locals_ref})
        score = next(item for item in variables["body"]["variables"] if item["name"] == "score")
        assert score["value"] == "1"
        assert score["evaluateName"] == "score"

        evaluated = request(adapter, 8, "evaluate", {"frameId": frame_id, "expression": "score"})
        assert evaluated["body"]["result"] == "1"

        request(adapter, 9, "continue", {"threadId": 1})
        terminated = wait_for_event(adapter, "terminated")
        assert terminated["event"] == "terminated"

        output = [
            message["body"]["output"]
            for message in decode_messages(adapter.writer.getvalue())
            if message.get("event") == "output"
        ]
        assert "3\n" in output


def test_stop_on_entry_and_step() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        program = Path(tmp) / "main.sprout"
        program.write_text("value = 1\nvalue = value + 1\nsay value\n", encoding="utf-8")
        adapter = DAP.SproutDebugAdapter(reader=io.BytesIO(), writer=io.BytesIO())
        request(adapter, 1, "initialize")
        request(adapter, 2, "launch", {"program": str(program), "stopOnEntry": True})
        before_start = len(decode_messages(adapter.writer.getvalue()))
        request(adapter, 3, "configurationDone")
        entry = wait_for_event(adapter, "stopped", before_start)
        assert entry["body"]["reason"] == "entry"

        before_step = len(decode_messages(adapter.writer.getvalue()))
        request(adapter, 4, "next", {"threadId": 1})
        stepped = wait_for_event(adapter, "stopped", before_step)
        assert stepped["body"]["reason"] == "step"
        stack = request(adapter, 5, "stackTrace", {"threadId": 1})
        assert stack["body"]["stackFrames"][0]["line"] == 2
        request(adapter, 6, "continue", {"threadId": 1})
        wait_for_event(adapter, "terminated")


def test_conditional_hit_breakpoint_and_expression_evaluation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        program = Path(tmp) / "main.sprout"
        program.write_text("i = 0\nwhile i < 4:\n  i = i + 1\nsay i\n", encoding="utf-8")
        adapter = DAP.SproutDebugAdapter(reader=io.BytesIO(), writer=io.BytesIO())
        initialized = request(adapter, 1, "initialize")
        assert initialized["body"]["supportsConditionalBreakpoints"] is True
        assert initialized["body"]["supportsHitConditionalBreakpoints"] is True
        request(adapter, 2, "launch", {"program": str(program)})
        request(adapter, 3, "setBreakpoints", {
            "source": {"path": str(program)},
            "breakpoints": [{"line": 3, "condition": "i >= 1", "hitCondition": "2"}],
        })
        before_start = len(decode_messages(adapter.writer.getvalue()))
        request(adapter, 4, "configurationDone")
        stopped = wait_for_event(adapter, "stopped", before_start)
        assert stopped["body"]["reason"] == "breakpoint"
        stack = request(adapter, 5, "stackTrace", {"threadId": 1})
        frame_id = stack["body"]["stackFrames"][0]["id"]
        evaluated = request(adapter, 6, "evaluate", {"frameId": frame_id, "expression": "i + 10"})
        assert evaluated["body"]["result"] == "11"
        request(adapter, 7, "continue", {"threadId": 1})
        wait_for_event(adapter, "terminated")


def test_instance_fields_omit_bare_evaluate_name() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        program = Path(tmp) / "main.sprout"
        program.write_text(
            "class Player:\n"
            "  def init(self, name):\n"
            "    self.name = name\n\n"
            "  def show(self):\n"
            "    say self.name\n\n"
            'player = Player("Mina")\n'
            "player.show()\n",
            encoding="utf-8",
        )
        adapter = DAP.SproutDebugAdapter(reader=io.BytesIO(), writer=io.BytesIO())
        request(adapter, 1, "initialize")
        request(adapter, 2, "launch", {"program": str(program)})
        request(adapter, 3, "setBreakpoints", {
            "source": {"path": str(program)},
            "breakpoints": [{"line": 6}],
        })
        before_start = len(decode_messages(adapter.writer.getvalue()))
        request(adapter, 4, "configurationDone")
        wait_for_event(adapter, "stopped", before_start)
        stack = request(adapter, 5, "stackTrace", {"threadId": 1})
        frame_id = stack["body"]["stackFrames"][0]["id"]
        scopes = request(adapter, 6, "scopes", {"frameId": frame_id})
        locals_ref = scopes["body"]["scopes"][0]["variablesReference"]
        variables = request(adapter, 7, "variables", {"variablesReference": locals_ref})
        self_var = next(item for item in variables["body"]["variables"] if item["name"] == "self")
        self_fields = request(adapter, 8, "variables", {"variablesReference": self_var["variablesReference"]})
        name_field = next(item for item in self_fields["body"]["variables"] if item["name"] == "name")
        assert "evaluateName" not in name_field
        request(adapter, 9, "continue", {"threadId": 1})
        wait_for_event(adapter, "terminated")


def test_uncaught_exception_breakpoint() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        program = Path(tmp) / "main.sprout"
        program.write_text('raise "broken"\n', encoding="utf-8")
        adapter = DAP.SproutDebugAdapter(reader=io.BytesIO(), writer=io.BytesIO())
        initialized = request(adapter, 1, "initialize")
        assert initialized["body"]["exceptionBreakpointFilters"][0]["filter"] == "uncaught"
        request(adapter, 2, "launch", {"program": str(program)})
        request(adapter, 3, "setExceptionBreakpoints", {"filters": ["uncaught"]})
        before_start = len(decode_messages(adapter.writer.getvalue()))
        request(adapter, 4, "configurationDone")
        stopped = wait_for_event(adapter, "stopped", before_start)
        assert stopped["body"]["reason"] == "exception"
        info = request(adapter, 5, "exceptionInfo", {"threadId": 1})
        assert "broken" in info["body"]["description"]
        request(adapter, 6, "continue", {"threadId": 1})
        wait_for_event(adapter, "terminated")


def main() -> int:
    test_breakpoint_stack_variables_and_continue()
    test_stop_on_entry_and_step()
    test_conditional_hit_breakpoint_and_expression_evaluation()
    test_instance_fields_omit_bare_evaluate_name()
    test_uncaught_exception_breakpoint()
    print("sprout debug adapter tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
