from __future__ import annotations

import json
import http.server
import math
import queue
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from .model import SproutError, SproutRaised


class NativeResource:
    def get(self, name: str) -> Any:
        raise SproutError(f"{self.__class__.__name__} has no property '{name}'")

    def __repr__(self) -> str:
        return f"<native {self.__class__.__name__}>"


class NativeCall:
    def __init__(self, name: str, fn: Callable[..., Any], arity: int | None = None):
        self.name = name
        self.fn = fn
        self.arity = arity

    def call(self, _interpreter: Any, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        if kwargs:
            raise SproutError(f"{self.name} does not accept keyword args")
        if self.arity is not None and len(args) != self.arity:
            raise SproutError(f"{self.name} expected {self.arity} args, got {len(args)}")
        return self.fn(*args)


class Expectation(NativeResource):
    def __init__(self, actual: Any):
        self.actual = actual

    def get(self, name: str) -> Any:
        methods = {
            "to_equal": NativeCall("expect.to_equal", self.to_equal, 1),
            "not_to_equal": NativeCall("expect.not_to_equal", self.not_to_equal, 1),
            "to_be_true": NativeCall("expect.to_be_true", self.to_be_true, 0),
            "to_be_false": NativeCall("expect.to_be_false", self.to_be_false, 0),
            "to_contain": NativeCall("expect.to_contain", self.to_contain, 1),
        }
        if name in methods:
            return methods[name]
        return super().get(name)

    def fail(self, message: str) -> None:
        raise SproutRaised(message)

    def to_equal(self, expected: Any) -> bool:
        if self.actual != expected:
            self.fail(f"expected {self.actual!r} to equal {expected!r}")
        return True

    def not_to_equal(self, expected: Any) -> bool:
        if self.actual == expected:
            self.fail(f"expected {self.actual!r} not to equal {expected!r}")
        return True

    def to_be_true(self) -> bool:
        if self.actual is not True:
            self.fail(f"expected {self.actual!r} to be true")
        return True

    def to_be_false(self) -> bool:
        if self.actual is not False:
            self.fail(f"expected {self.actual!r} to be false")
        return True

    def to_contain(self, expected: Any) -> bool:
        try:
            passed = expected in self.actual
        except TypeError:
            passed = False
        if not passed:
            self.fail(f"expected {self.actual!r} to contain {expected!r}")
        return True


class TaskFuture(NativeResource):
    def __init__(self, future: Future[Any]):
        self.future = future

    def get(self, name: str) -> Any:
        if name == "done":
            return self.future.done()
        if name == "cancelled":
            return self.future.cancelled()
        methods = {
            "result": NativeCall("task.result", self.result, None),
            "cancel": NativeCall("task.cancel", self.cancel, 0),
        }
        if name in methods:
            return methods[name]
        return super().get(name)

    def result(self, timeout: Any = None) -> Any:
        try:
            seconds = None if timeout is None else float(timeout)
            value = self.future.result(timeout=seconds)
            return value.result(timeout) if isinstance(value, TaskFuture) else value
        except Exception as exc:
            raise SproutError(f"Task failed: {exc}") from exc

    def cancel(self) -> bool:
        return self.future.cancel()


class StructuredTaskGroup(NativeResource):
    def __init__(self, spawn: Callable[[Any, list[Any]], TaskFuture]):
        self.spawn_task = spawn
        self.tasks: list[TaskFuture] = []
        self.closed = False

    def get(self, name: str) -> Any:
        if name == "count":
            return len(self.tasks)
        methods = {
            "spawn": NativeCall("taskgroup.spawn", self.spawn, None),
            "wait": NativeCall("taskgroup.wait", self.wait, 0),
            "cancel": NativeCall("taskgroup.cancel", self.cancel, 0),
        }
        if name in methods:
            return methods[name]
        return super().get(name)

    def spawn(self, callable_value: Any, *args: Any) -> TaskFuture:
        if self.closed:
            raise SproutError("Cannot spawn into a closed task group")
        task = self.spawn_task(callable_value, list(args))
        self.tasks.append(task)
        return task

    def wait(self) -> list[Any]:
        self.closed = True
        results = []
        try:
            for task in self.tasks:
                results.append(task.result())
        except Exception:
            self.cancel()
            raise
        return results

    def cancel(self) -> int:
        self.closed = True
        return sum(1 for task in self.tasks if task.cancel())

    def settle(self) -> None:
        for task in self.tasks:
            try:
                task.result()
            except Exception:
                pass


class MessageQueue(NativeResource):
    def __init__(self):
        self.queue: queue.Queue[Any] = queue.Queue()

    def get(self, name: str) -> Any:
        if name == "size":
            return self.queue.qsize()
        methods = {
            "send": NativeCall("queue.send", self.send, 1),
            "receive": NativeCall("queue.receive", self.receive, None),
            "empty": NativeCall("queue.empty", self.queue.empty, 0),
        }
        if name in methods:
            return methods[name]
        return super().get(name)

    def send(self, value: Any) -> Any:
        self.queue.put(value)
        return value

    def receive(self, timeout: Any = None) -> Any:
        try:
            seconds = None if timeout is None else float(timeout)
            return self.queue.get(timeout=seconds)
        except queue.Empty as exc:
            raise SproutError("Queue receive timed out") from exc


class HttpResponse(NativeResource):
    def __init__(self, status: int, text: str, headers: dict[str, str], url: str):
        self.status = status
        self.text = text
        self.headers = headers
        self.url = url

    def get(self, name: str) -> Any:
        values = {
            "status": self.status,
            "ok": 200 <= self.status < 300,
            "text": self.text,
            "headers": self.headers,
            "url": self.url,
            "json": NativeCall("http_response.json", self.json, 0),
        }
        if name in values:
            return values[name]
        return super().get(name)

    def json(self) -> Any:
        try:
            return json.loads(self.text)
        except json.JSONDecodeError as exc:
            raise SproutError(f"HTTP response is not valid JSON: {exc}") from exc


class RouteHttpServer(NativeResource):
    def __init__(self, routes: dict[str, Any], host: str = "127.0.0.1", port: int = 0):
        self.routes = routes
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                route = outer.routes.get(self.path)
                if route is None:
                    self.send_response(404)
                    body = b"not found"
                    content_type = "text/plain; charset=utf-8"
                else:
                    status = int(route.get("status", 200)) if isinstance(route, dict) else 200
                    value = route.get("body", "") if isinstance(route, dict) else route
                    if isinstance(value, (dict, list)):
                        body = json.dumps(value).encode("utf-8")
                        content_type = "application/json"
                    else:
                        body = str(value).encode("utf-8")
                        content_type = "text/plain; charset=utf-8"
                    self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *_args: Any) -> None:
                return

        self.server = http.server.ThreadingHTTPServer((host, int(port)), Handler)
        actual_host, actual_port = self.server.server_address[:2]
        self.url = f"http://{actual_host}:{actual_port}"
        self.thread: threading.Thread | None = None

    def get(self, name: str) -> Any:
        if name == "url":
            return self.url
        methods = {
            "start": NativeCall("http_server.start", self.start, 0),
            "stop": NativeCall("http_server.stop", self.stop, 0),
        }
        if name in methods:
            return methods[name]
        return super().get(name)

    def start(self) -> str:
        if self.thread and self.thread.is_alive():
            return self.url
        self.thread = threading.Thread(target=self.server.serve_forever, name="sprout-http", daemon=True)
        self.thread.start()
        return self.url

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2)


class SQLiteDatabase(NativeResource):
    def __init__(self, path: str):
        try:
            self.connection = sqlite3.connect(path)
            self.connection.row_factory = sqlite3.Row
            self.in_transaction = False
        except sqlite3.Error as exc:
            raise SproutError(f"Could not open SQLite database: {exc}") from exc

    def get(self, name: str) -> Any:
        methods = {
            "execute": NativeCall("sqlite.execute", self.execute, None),
            "query": NativeCall("sqlite.query", self.query, None),
            "begin": NativeCall("sqlite.begin", self.begin, 0),
            "commit": NativeCall("sqlite.commit", self.commit, 0),
            "rollback": NativeCall("sqlite.rollback", self.rollback, 0),
            "close": NativeCall("sqlite.close", self.close, 0),
        }
        if name in methods:
            return methods[name]
        return super().get(name)

    def execute(self, sql: Any, params: Any = None) -> int:
        try:
            cursor = self.connection.execute(str(sql), list(params or []))
            if not self.in_transaction:
                self.connection.commit()
            return cursor.rowcount
        except sqlite3.Error as exc:
            raise SproutError(f"SQLite execute failed: {exc}") from exc

    def query(self, sql: Any, params: Any = None) -> list[dict[str, Any]]:
        try:
            cursor = self.connection.execute(str(sql), list(params or []))
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            raise SproutError(f"SQLite query failed: {exc}") from exc

    def begin(self) -> None:
        if self.in_transaction:
            raise SproutError("SQLite transaction is already active")
        self.connection.execute("BEGIN")
        self.in_transaction = True

    def commit(self) -> None:
        self.connection.commit()
        self.in_transaction = False

    def rollback(self) -> None:
        self.connection.rollback()
        self.in_transaction = False

    def close(self) -> None:
        self.connection.close()


TASK_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="sprout-task")


def submit_task(fn: Callable[[], Any], delay: float = 0.0) -> TaskFuture:
    def run() -> Any:
        if delay > 0:
            time.sleep(delay)
        return fn()

    return TaskFuture(TASK_POOL.submit(run))


def http_request(method: Any, url: Any, data: Any = None, headers: Any = None, timeout: Any = 10) -> HttpResponse:
    body = None
    request_headers = {str(key): str(value) for key, value in dict(headers or {}).items()}
    if data is not None:
        if isinstance(data, (dict, list)):
            body = json.dumps(data).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        else:
            body = str(data).encode("utf-8")
    request = urllib.request.Request(str(url), data=body, headers=request_headers, method=str(method).upper())
    try:
        with urllib.request.urlopen(request, timeout=float(timeout)) as response:
            text = response.read().decode("utf-8", errors="replace")
            status = int(getattr(response, "status", 200) or 200)
            response_url = response.geturl() if hasattr(response, "geturl") else str(url)
            return HttpResponse(status, text, dict(response.headers.items()), response_url)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return HttpResponse(exc.code, text, dict(exc.headers.items()), exc.url)
    except urllib.error.URLError as exc:
        raise SproutError(f"HTTP request failed: {exc.reason}") from exc


def vec_add(a: Any, b: Any) -> list[float]:
    return [float(x) + float(y) for x, y in zip(a, b)]


def vec_sub(a: Any, b: Any) -> list[float]:
    return [float(x) - float(y) for x, y in zip(a, b)]


def vec_dot(a: Any, b: Any) -> float:
    return sum(float(x) * float(y) for x, y in zip(a, b))


def vec_magnitude(value: Any) -> float:
    return math.sqrt(vec_dot(value, value))


def vec_normalize(value: Any) -> list[float]:
    magnitude = vec_magnitude(value)
    if magnitude == 0:
        return [0.0 for _ in value]
    return [float(item) / magnitude for item in value]


def mat_mul(a: Any, b: Any) -> list[list[float]]:
    if not a or not b:
        return []
    columns = list(zip(*b))
    return [[sum(float(x) * float(y) for x, y in zip(row, column)) for column in columns] for row in a]


UNIT_FACTORS = {
    "m": 1.0,
    "cm": 0.01,
    "mm": 0.001,
    "km": 1000.0,
    "in": 0.0254,
    "ft": 0.3048,
    "kg": 1.0,
    "g": 0.001,
    "lb": 0.45359237,
    "s": 1.0,
    "ms": 0.001,
    "min": 60.0,
    "h": 3600.0,
}


STANDARD_LIBRARY_GROUPS = {
    "core": ["len", "range", "str", "int", "num", "type", "ensure", "fail"],
    "math": ["round", "sqrt", "sin", "cos", "lerp", "interpolate"],
    "strings": ["trim", "upper", "lower", "replace", "join"],
    "files": ["readfile", "writefile", "appendfile", "exists", "listdir"],
    "json": ["readjson", "writejson", "json_parse", "json_stringify"],
    "testing": ["expect", "ensure", "fail"],
    "async": ["task_spawn", "task_after", "task_wait_all", "queue_open"],
    "http": ["http_request", "http_get", "http_post", "http_server"],
    "sqlite": ["sqlite_open", "sqlite_exec", "sqlite_query", "sqlite_begin", "sqlite_commit", "sqlite_rollback", "sqlite_close"],
    "engineering": ["vec_add", "vec_sub", "vec_dot", "vec_magnitude", "vec_normalize", "mat_mul", "unit_convert", "kinetic_energy", "force", "pressure"],
    "game": ["examples/modules/appgame.sprout", "PixelGarden", "StarBloom3D", "Window2D", "PandaWindow3D"],
}


def convert_unit(value: Any, source: Any, target: Any) -> float:
    source_name = str(source)
    target_name = str(target)
    if source_name not in UNIT_FACTORS or target_name not in UNIT_FACTORS:
        raise SproutError(f"Unknown unit conversion: {source_name} -> {target_name}")
    return float(value) * UNIT_FACTORS[source_name] / UNIT_FACTORS[target_name]
