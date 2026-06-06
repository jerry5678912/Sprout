#!/usr/bin/env python3
"""Debug Adapter Protocol server for Sprout's experimental bytecode VM."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
from typing import Any, BinaryIO


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sprout_core.bytecode import (  # noqa: E402
    BytecodeVM,
    CodeObject,
    DebugFrame,
    Instruction,
    VMInstance,
    compile_file,
)
from sprout_core.model import SproutError, SproutRaised  # noqa: E402
from sprout_core.runtime import Builtin, Env, Interpreter, format_error, format_value, truthy, type_name  # noqa: E402
from sprout_core.tooling import parse_source  # noqa: E402


class DebugController:
    def __init__(self, on_stop):
        self.on_stop = on_stop
        self.condition = threading.Condition()
        self.breakpoints: dict[str, list[dict[str, Any]]] = {}
        self.break_on_uncaught = False
        self.mode = "continue"
        self.paused = False
        self.pause_requested = False
        self.stop_on_entry = False
        self.entry_seen = False
        self.target_depth = 0
        self.last_location: tuple[str | None, int | None] | None = None
        self.vm: BytecodeVM | None = None
        self.last_exception: Exception | None = None

    def set_breakpoints(self, path: str, breakpoints: list[dict[str, Any]]) -> None:
        self.breakpoints[os.path.realpath(path)] = breakpoints

    def evaluate_expression(self, expression: str, env: Env) -> Any:
        statement = parse_source(f"say {expression}\n")[0]
        interpreter = Interpreter(source_path=self.vm.interpreter.source_path if self.vm else None)
        interpreter.env = env
        interpreter.globals = self.vm.globals if self.vm else env
        return interpreter.evaluate(statement[1][0])

    def hit_condition_matches(self, condition: str, count: int) -> bool:
        text = condition.strip()
        if not text:
            return True
        if text.isdigit():
            return count == int(text)
        for operator in (">=", "<=", ">", "<", "=="):
            if text.startswith(operator) and text[len(operator):].strip().isdigit():
                target = int(text[len(operator):].strip())
                return {
                    ">=": count >= target,
                    "<=": count <= target,
                    ">": count > target,
                    "<": count < target,
                    "==": count == target,
                }[operator]
        if text.startswith("%") and text[1:].strip().isdigit():
            divisor = int(text[1:].strip())
            return divisor > 0 and count % divisor == 0
        return False

    def breakpoint_matches(self, path: str, line: int, env: Env) -> bool:
        for breakpoint in self.breakpoints.get(path, []):
            if breakpoint["line"] != line:
                continue
            breakpoint["hits"] += 1
            if not self.hit_condition_matches(str(breakpoint.get("hitCondition") or ""), breakpoint["hits"]):
                continue
            condition = str(breakpoint.get("condition") or "").strip()
            if condition:
                try:
                    if not truthy(self.evaluate_expression(condition, env)):
                        continue
                except Exception:
                    continue
            return True
        return False

    def before_instruction(self, vm: BytecodeVM, instr: Instruction, _env: Env) -> None:
        self.vm = vm
        path = os.path.realpath(instr.source) if instr.source else None
        location = (path, instr.line)
        changed_line = location != self.last_location
        depth = len(vm.debug_frames)
        reason = None
        if self.stop_on_entry and not self.entry_seen:
            self.entry_seen = True
            reason = "entry"
        elif self.pause_requested:
            self.pause_requested = False
            reason = "pause"
        elif changed_line and path and instr.line and self.breakpoint_matches(path, instr.line, _env):
            reason = "breakpoint"
        elif changed_line and self.mode == "stepIn":
            reason = "step"
        elif changed_line and self.mode == "next" and depth <= self.target_depth:
            reason = "step"
        elif changed_line and self.mode == "stepOut" and depth < self.target_depth:
            reason = "step"
        self.last_location = location
        if reason:
            with self.condition:
                self.paused = True
                self.mode = "paused"
                self.on_stop(reason)
                while self.paused:
                    self.condition.wait()

    def on_exception(self, vm: BytecodeVM, _exc: Exception) -> None:
        self.vm = vm
        self.last_exception = _exc
        if not self.break_on_uncaught:
            return
        with self.condition:
            self.paused = True
            self.mode = "paused"
            self.on_stop("exception")
            while self.paused:
                self.condition.wait()

    def resume(self, mode: str, depth: int | None = None) -> None:
        with self.condition:
            self.mode = mode
            self.target_depth = depth if depth is not None else len(self.vm.debug_frames if self.vm else [])
            self.paused = False
            self.condition.notify_all()

    def pause(self) -> None:
        self.pause_requested = True


class SproutDebugAdapter:
    def __init__(self, reader: BinaryIO | None = None, writer: BinaryIO | None = None):
        self.reader = reader or sys.stdin.buffer
        self.writer = writer or sys.stdout.buffer
        self.write_lock = threading.Lock()
        self.sequence = 1
        self.program = ""
        self.args: list[str] = []
        self.code: CodeObject | None = None
        self.controller = DebugController(self.stopped)
        self.worker: threading.Thread | None = None
        self.vm: BytecodeVM | None = None
        self.frame_handles: dict[int, DebugFrame] = {}
        self.variable_handles: dict[int, Any] = {}
        self.next_handle = 1
        self.terminated = False

    def read_message(self) -> dict[str, Any] | None:
        headers: dict[str, str] = {}
        while True:
            line = self.reader.readline()
            if not line:
                return None
            decoded = line.decode("ascii", errors="replace").strip()
            if not decoded:
                break
            key, value = decoded.split(":", 1)
            headers[key.lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        if length <= 0:
            return None
        return json.loads(self.reader.read(length).decode("utf-8"))

    def send(self, payload: dict[str, Any]) -> None:
        payload.setdefault("seq", self.sequence)
        self.sequence += 1
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        with self.write_lock:
            self.writer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii"))
            self.writer.write(raw)
            self.writer.flush()

    def response(self, request: dict[str, Any], body: Any = None, success: bool = True, message: str | None = None) -> None:
        payload = {
            "type": "response",
            "request_seq": request.get("seq", 0),
            "command": request.get("command", ""),
            "success": success,
        }
        if body is not None:
            payload["body"] = body
        if message:
            payload["message"] = message
        self.send(payload)

    def event(self, name: str, body: Any = None) -> None:
        payload = {"type": "event", "event": name}
        if body is not None:
            payload["body"] = body
        self.send(payload)

    def stopped(self, reason: str) -> None:
        self.event("stopped", {"reason": reason, "threadId": 1, "allThreadsStopped": True})

    def executable_lines(self, code: CodeObject) -> set[int]:
        lines = {instr.line for instr in code.instructions if instr.line}
        for instr in code.instructions:
            if instr.op == "MAKE_FUNCTION":
                lines.update(self.executable_lines(instr.arg[1]))
            elif instr.op == "MAKE_CLASS":
                for _name, child in instr.arg[1]:
                    lines.update(self.executable_lines(child))
        return {int(line) for line in lines}

    def launch(self, arguments: dict[str, Any]) -> None:
        self.program = os.path.realpath(os.path.abspath(str(arguments.get("program", ""))))
        self.args = [str(item) for item in arguments.get("args", [])]
        self.controller.stop_on_entry = bool(arguments.get("stopOnEntry", False))
        self.code = compile_file(self.program)

    def start_program(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        def run() -> None:
            try:
                self.vm = BytecodeVM(self.program, argv=self.args, debug_controller=self.controller)
                self.controller.vm = self.vm
                printer = Builtin("print", None, lambda *values: self.output(" ".join(format_value(value) for value in values) + "\n"))
                self.vm.globals.define("print", printer)
                self.vm.globals.define("say", printer)
                self.vm.run(self.code)
                self.event("exited", {"exitCode": 0})
            except (SproutError, SproutRaised) as exc:
                if isinstance(exc, SproutError):
                    text = format_error(exc)
                else:
                    text = f"error: RaisedError: {format_value(exc.value)}"
                self.output(text + "\n", "stderr")
                self.event("exited", {"exitCode": 1})
            except Exception as exc:
                self.output(f"error: InternalError: {exc}\n", "stderr")
                self.event("exited", {"exitCode": 1})
            finally:
                self.terminated = True
                self.event("terminated")

        self.worker = threading.Thread(target=run, name="sprout-debuggee", daemon=True)
        self.worker.start()

    def output(self, text: str, category: str = "stdout") -> None:
        self.event("output", {"category": category, "output": text})

    def add_handle(self, value: Any) -> int:
        handle = self.next_handle
        self.next_handle += 1
        self.variable_handles[handle] = value
        return handle

    def variable(self, name: str, value: Any) -> dict[str, Any]:
        expandable = isinstance(value, (list, dict, Env, VMInstance))
        return {
            "name": name,
            "value": format_value(value),
            "type": type_name(value),
            "variablesReference": self.add_handle(value) if expandable else 0,
        }

    def variables_for(self, value: Any) -> list[dict[str, Any]]:
        if isinstance(value, Env):
            return [self.variable(name, item) for name, item in sorted(value.values.items())]
        if isinstance(value, VMInstance):
            return [self.variable(name, item) for name, item in sorted(value.fields.items())]
        if isinstance(value, list):
            return [self.variable(str(index), item) for index, item in enumerate(value)]
        if isinstance(value, dict):
            return [self.variable(format_value(key), item) for key, item in value.items()]
        return []

    def current_frames(self) -> list[DebugFrame]:
        return list(reversed(self.vm.debug_frames if self.vm else []))

    def handle(self, request: dict[str, Any]) -> bool:
        command = request.get("command", "")
        arguments = request.get("arguments") or {}
        if command == "initialize":
            self.response(request, {
                "supportsConfigurationDoneRequest": True,
                "supportsEvaluateForHovers": True,
                "supportsSetVariable": False,
                "supportsTerminateRequest": True,
                "supportsConditionalBreakpoints": True,
                "supportsHitConditionalBreakpoints": True,
                "supportsExceptionFilterOptions": True,
                "exceptionBreakpointFilters": [
                    {
                        "filter": "uncaught",
                        "label": "Uncaught Sprout errors",
                        "description": "Pause before an uncaught Sprout error terminates the program.",
                        "default": False,
                    }
                ],
            })
            self.event("initialized")
        elif command == "launch":
            try:
                self.launch(arguments)
                self.response(request)
            except Exception as exc:
                self.response(request, success=False, message=str(exc))
        elif command == "setBreakpoints":
            source_path = (arguments.get("source") or {}).get("path", self.program)
            requested = [
                {
                    "line": int(item.get("line", 0)),
                    "condition": item.get("condition"),
                    "hitCondition": item.get("hitCondition"),
                    "hits": 0,
                }
                for item in arguments.get("breakpoints", [])
            ]
            available = self.executable_lines(self.code) if self.code else set()
            self.controller.set_breakpoints(source_path, requested)
            self.response(request, {
                "breakpoints": [
                    {
                        "verified": item["line"] in available,
                        "line": item["line"],
                        "source": {"path": source_path},
                    }
                    for item in requested
                ]
            })
        elif command == "setExceptionBreakpoints":
            self.controller.break_on_uncaught = "uncaught" in arguments.get("filters", [])
            self.response(request)
        elif command == "configurationDone":
            self.response(request)
            self.start_program()
        elif command == "threads":
            self.response(request, {"threads": [{"id": 1, "name": "Sprout main"}]})
        elif command == "stackTrace":
            self.frame_handles = {}
            frames = []
            for index, frame in enumerate(self.current_frames(), start=1):
                self.frame_handles[index] = frame
                instr = frame.instruction
                frames.append({
                    "id": index,
                    "name": frame.code.name,
                    "line": instr.line if instr and instr.line else 1,
                    "column": instr.col if instr and instr.col else 1,
                    "source": {"name": os.path.basename(instr.source), "path": instr.source} if instr and instr.source else None,
                })
            self.response(request, {"stackFrames": frames, "totalFrames": len(frames)})
        elif command == "scopes":
            frame = self.frame_handles.get(int(arguments.get("frameId", 0)))
            scopes = []
            if frame:
                scopes = [
                    {"name": "Locals", "variablesReference": self.add_handle(frame.env), "expensive": False},
                    {"name": "Value Stack", "variablesReference": self.add_handle(list(self.vm.stack if self.vm else [])), "expensive": False},
                ]
                if self.vm:
                    scopes.append({"name": "Globals", "variablesReference": self.add_handle(self.vm.globals), "expensive": True})
            self.response(request, {"scopes": scopes})
        elif command == "variables":
            value = self.variable_handles.get(int(arguments.get("variablesReference", 0)))
            self.response(request, {"variables": self.variables_for(value)})
        elif command == "evaluate":
            frame = self.frame_handles.get(int(arguments.get("frameId", 0)))
            expression = str(arguments.get("expression", "")).strip()
            try:
                value = self.controller.evaluate_expression(expression, frame.env) if frame and expression else None
                item = self.variable(expression, value)
                self.response(request, {
                    "result": item["value"],
                    "type": item["type"],
                    "variablesReference": item["variablesReference"],
                })
            except SproutError as exc:
                self.response(request, success=False, message=str(exc))
        elif command == "exceptionInfo":
            exc = self.controller.last_exception
            description = (
                format_error(exc)
                if isinstance(exc, SproutError)
                else f"RaisedError: {format_value(exc.value)}"
                if isinstance(exc, SproutRaised)
                else str(exc or "Unknown Sprout error")
            )
            self.response(request, {
                "exceptionId": type(exc).__name__ if exc else "SproutError",
                "description": description,
                "breakMode": "unhandled",
            })
        elif command in {"continue", "next", "stepIn", "stepOut"}:
            depth = len(self.vm.debug_frames if self.vm else [])
            mode = {"continue": "continue", "next": "next", "stepIn": "stepIn", "stepOut": "stepOut"}[command]
            self.response(request, {"allThreadsContinued": True} if command == "continue" else None)
            self.event("continued", {"threadId": 1, "allThreadsContinued": True})
            self.controller.resume(mode, depth)
        elif command == "pause":
            self.controller.pause()
            self.response(request)
        elif command in {"disconnect", "terminate"}:
            self.controller.resume("continue")
            self.response(request)
            return False
        else:
            self.response(request, success=False, message=f"Unsupported debug request: {command}")
        return True

    def run(self) -> int:
        while True:
            request = self.read_message()
            if request is None:
                return 0
            if request.get("type") != "request":
                continue
            if not self.handle(request):
                return 0


def main() -> int:
    return SproutDebugAdapter().run()


if __name__ == "__main__":
    raise SystemExit(main())
