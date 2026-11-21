"""pytest 的实际用例身份与状态；不看终端摘要、不接收 suite 自报通过。"""
import inspect
import json
import os
from pathlib import Path

import pytest


class Execution:
    def __init__(self):
        self.entries = {}

    @pytest.hookimpl
    def pytest_runtest_protocol(self, item):
        implementation = inspect.unwrap(item.function) if isinstance(item, pytest.Function) else None
        code = getattr(implementation, "__code__", None)
        if item.nodeid in self.entries:
            raise RuntimeError("duplicate test identity")
        self.entries[item.nodeid] = {"name": item.nodeid, "source": code.co_filename if code else "",
                                     "line": code.co_firstlineno if code else 0, "phases": {}}

    @pytest.hookimpl
    def pytest_runtest_logreport(self, report):
        item = self.entries[report.nodeid]
        if report.when in item["phases"]:
            raise RuntimeError("duplicate test phase")
        item["phases"][report.when] = ("skipped" if hasattr(report, "wasxfail") else report.outcome)

    @pytest.hookimpl
    def pytest_sessionfinish(self, session):
        rows = []
        for entry in self.entries.values():
            phases = entry.pop("phases")
            if "failed" in phases.values():
                status = "failed"
            elif "skipped" in phases.values():
                status = "skipped"
            elif len(phases) == 3 and set(phases.values()) == {"passed"}:
                status = "passed"
            else:
                status = "missing"
            rows.append(dict(entry, status=status))
        target = Path(os.environ["AT18_FRAMEWORK_FILE"])
        with target.open("x", encoding="utf-8") as stream:
            json.dump(rows, stream)


def pytest_configure(config):
    config.pluginmanager.register(Execution(), "at18-execution")
