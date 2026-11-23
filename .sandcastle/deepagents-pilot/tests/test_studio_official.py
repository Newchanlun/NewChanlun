import asyncio
import json
import shutil
import sqlite3
import uuid
from pathlib import Path

import conftest
import pytest
import v2env
from fake_github import FakeGitHub
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from test_agent import call, scripted
from v2env import TICKET, V2Env

from pilot1742 import run as pilot_run
from pilot1742 import studio
from pilot1742.agent import build_agent
from pilot1742.approval import SignedApprovals
from pilot1742.github_app import AppIdentity
from pilot1742.run import Busy
from pilot1742.studio_binding import (
    _LEASE,
    RunBoundCheckpointer,
    UnboundThreadWrite,
    grant,
    thread_for,
)
from pilot1742.workunit import DEDICATED_MARKER


@pytest.fixture(scope="module")
def _v2_seed(tmp_path_factory):
    root = tmp_path_factory.mktemp("studio_official_seed")
    seed = V2Env(root)
    return seed.source, seed.base, seed.bare, seed.identity.private_key_path


@pytest.fixture(autouse=True)
def _fast_env(monkeypatch, _v2_seed):
    seed_source, seed_base, seed_bare, seed_pem = _v2_seed
    orig_ensure = pilot_run.PilotRun._ensure_checkout
    real_sleep = pilot_run.time.sleep

    def _fast_env_init(self, tmp: Path):
        self.home = tmp / "home"
        self.source = tmp / "source"
        shutil.copytree(seed_source, self.source)
        self.base = seed_base
        self.home.mkdir()
        self.control({})

    def _fast_v2_init(self, tmp: Path):
        _fast_env_init(self, tmp)
        self.tmp = tmp
        self.bare = tmp / "origin.git"
        shutil.copytree(seed_bare, self.bare)
        pem = tmp / "app.pem"
        shutil.copy2(seed_pem, pem)
        pem.chmod(0o600)
        self.identity = AppIdentity(
            5486877, 179444545, 1150335160, "Newchanlun/NewChanlun", "newchanlun-deepagents-1742", pem
        )
        self.github = FakeGitHub(self.identity, self.bare)
        self.github.add_issue(TICKET, body=f"#1742 首证专用票\n\n{DEDICATED_MARKER}\n")
        self.claims_root = tmp / "claims"
        self.workers_log = tmp / "workers.jsonl"
        self.workers_log.write_text(json.dumps({"ticket": 1715, "branch": "sandcastle/issue-1715"}) + "\n")
        self.approvals = SignedApprovals(
            trust_path=tmp / "unconfigured-trust.json",
            authority_root=tmp / "unconfigured-authority",
        )

    def _fast_ensure(self, role, head):
        path, branch = self.spec.checkout_for(role), self.spec.branch_for(role)
        if not path.exists():
            src = Path(self.source_repo)
            git_dir = src / ".git"
            branch_ref = git_dir / "refs" / "heads" / branch
            head_file = git_dir / "HEAD"
            main_ref = git_dir / "refs" / "heads" / "main"
            index_file = git_dir / "index"
            wt_name = f"{self.spec.run_id}-{role}"
            wt_admin = git_dir / "worktrees" / wt_name
            if (
                git_dir.is_dir()
                and not (git_dir / "packed-refs").exists()
                and not branch_ref.exists()
                and not wt_admin.exists()
                and head_file.is_file()
                and head_file.read_text().strip() == "ref: refs/heads/main"
                and main_ref.is_file()
                and main_ref.read_text().strip() == str(head)
                and index_file.is_file()
            ):
                pilot_run.require_free_space(path.parent)
                path.mkdir(parents=True, exist_ok=True)
                branch_ref.parent.mkdir(parents=True, exist_ok=True)
                branch_ref.write_text(f"{head}\n")
                wt_admin.mkdir(parents=True)
                (wt_admin / "HEAD").write_text(f"ref: refs/heads/{branch}\n")
                (wt_admin / "commondir").write_text("../..\n")
                (wt_admin / "gitdir").write_text(f"{path / '.git'}\n")
                shutil.copy2(index_file, wt_admin / "index")
                for item in src.iterdir():
                    if item.name == ".git":
                        continue
                    dst = path / item.name
                    if item.is_dir() and not item.is_symlink():
                        shutil.copytree(item, dst, symlinks=True)
                    else:
                        shutil.copy2(item, dst, follow_symlinks=False)
                (path / ".git").write_text(f"gitdir: {wt_admin}\n")
                self.trail("checkout_created", role=role, path=str(path), branch=branch)
                return
        return orig_ensure(self, role, head)

    monkeypatch.setattr(conftest.Env, "__init__", _fast_env_init)
    monkeypatch.setattr(v2env.V2Env, "__init__", _fast_v2_init)
    monkeypatch.setattr(pilot_run.PilotRun, "_ensure_checkout", _fast_ensure)
    monkeypatch.setattr(pilot_run.time, "sleep", lambda sec: real_sleep(min(sec, 0.01)))

ALL = ["GET", "POST", "PUT", "PATCH", "DELETE"]


@pytest.fixture
def v2(tmp_path):
    return V2Env(tmp_path)


@pytest.fixture
def bound(v2, monkeypatch):
    unit = v2.register()
    v2.run(unit).release()
    monkeypatch.setenv("PILOT1742_STATE_ROOT", str(v2.home))
    monkeypatch.setenv("PILOT1742_STUDIO_RUNS", unit.run_id)
    monkeypatch.setattr(studio, "OPEN_BOUND", lambda run_id: v2.run(v2.load(run_id)))
    return unit


def cli_checkpoint(v2, unit):
    run = v2.run(unit)
    model = scripted(call("run_status"), AIMessage("看过状态"))
    agent = build_agent(run, SqliteSaver(sqlite3.connect(run.dir / "graph.sqlite", check_same_thread=False)), model)
    agent.invoke({"messages": [("user", "开始")]}, {"configurable": {"thread_id": unit.run_id}}, durability="sync")
    run.release()
    return run


def cli_paused(v2, unit, *, operator=True):
    """CLI 跑到一半停下：operator=True 停在操作员中断处（有 interrupt），False 停在待执行的 tools 前（只有 next）。"""
    run = v2.run(unit)
    model = scripted(call("run_status"), AIMessage("CLI 不该走到这里"))
    agent = build_agent(run, SqliteSaver(sqlite3.connect(run.dir / "graph.sqlite", check_same_thread=False)), model)
    config = {"configurable": {"thread_id": unit.run_id}}
    if operator:
        run.request_interrupt("operator")
        agent.invoke({"messages": [("user", "开始")]}, config, durability="sync")
    else:
        agent.invoke({"messages": [("user", "开始")]}, config, durability="sync", interrupt_before=["tools"])
    head = agent.get_state(config).config["configurable"]["checkpoint_id"]
    run.release()
    return run, head


def execution(unit, *, resume=True, checkpoint=None):
    return {"configurable": {"thread_id": thread_for(unit.run_id), "checkpoint_ns": "", "__is_for_execution__": True,
                             studio.EXPECT: {"resume": resume, "checkpoint": checkpoint}}}


def test_bound_thread_reads_the_cli_checkpoint_and_unbound_threads_store_nothing(v2, bound):
    run = cli_checkpoint(v2, bound)
    saver = SqliteSaver(sqlite3.connect(run.dir / "graph.sqlite", check_same_thread=False))
    cli = saver.get_tuple({"configurable": {"thread_id": bound.run_id, "checkpoint_ns": ""}})
    cp = RunBoundCheckpointer()
    thread = thread_for(bound.run_id)
    seen = asyncio.run(cp.aget_tuple({"configurable": {"thread_id": thread, "checkpoint_ns": ""}}))
    assert seen.checkpoint["id"] == cli.checkpoint["id"] and seen.config["configurable"]["thread_id"] == thread
    stranger = {"configurable": {"thread_id": str(uuid.uuid4()), "checkpoint_ns": ""}}
    assert asyncio.run(cp.aget_tuple(stranger)) is None
    with pytest.raises(UnboundThreadWrite, match="未绑定"):
        asyncio.run(cp.aput(stranger, cli.checkpoint, cli.metadata, {}))
    with pytest.raises(UnboundThreadWrite, match="不是持有 run"):
        asyncio.run(cp.aput({"configurable": {"thread_id": thread, "checkpoint_ns": ""}}, cli.checkpoint,
                            cli.metadata, {}))


def test_official_resume_holds_the_same_run_lock_and_continues_the_same_checkpoint(v2, bound, monkeypatch):
    run, head = cli_paused(v2, bound)
    monkeypatch.setattr(studio, "EXECUTION_MODEL", scripted(AIMessage("Studio 继续")))
    thread = thread_for(bound.run_id)

    async def official_run():
        async with studio.graph(execution(bound, checkpoint=head)) as agent:
            lease = _LEASE.get()
            assert lease is not None and lease.active and lease.run_id == bound.run_id
            assert run.interrupt_requested() is None
            with pytest.raises(Busy):
                v2.run(bound)
            served = agent.copy(update={"checkpointer": RunBoundCheckpointer()})
            await served.ainvoke(Command(resume={"approved": True}), {"configurable": {"thread_id": thread}})
        assert not lease.active

    asyncio.run(official_run())
    cli = build_agent(run, SqliteSaver(sqlite3.connect(run.dir / "graph.sqlite", check_same_thread=False)),
                      scripted())
    state = cli.get_state({"configurable": {"thread_id": bound.run_id}})
    assert [m.type for m in state.values["messages"]] == ["human", "ai", "tool", "ai"]
    assert state.values["messages"][-1].content == "Studio 继续" and not state.next
    v2.run(bound).release()


def test_official_continue_runs_the_pending_tools_of_a_stopped_run(v2, bound, monkeypatch):
    run, head = cli_paused(v2, bound, operator=False)
    monkeypatch.setattr(studio, "EXECUTION_MODEL", scripted(AIMessage("Studio 接着跑完")))
    thread = thread_for(bound.run_id)

    async def official_run():
        async with studio.graph(execution(bound, resume=False, checkpoint=head)) as agent:
            served = agent.copy(update={"checkpointer": RunBoundCheckpointer()})
            await served.ainvoke(None, {"configurable": {"thread_id": thread}})

    asyncio.run(official_run())
    cli = build_agent(run, SqliteSaver(sqlite3.connect(run.dir / "graph.sqlite", check_same_thread=False)),
                      scripted())
    messages = cli.get_state({"configurable": {"thread_id": bound.run_id}}).values["messages"]
    assert [m.type for m in messages] == ["human", "ai", "tool", "ai"] and messages[-1].content == "Studio 接着跑完"
    v2.run(bound).release()


def test_continue_keeps_a_stop_recorded_before_its_checkpoint(v2, bound, monkeypatch):
    from pilot1742.cli import drive

    run, head = cli_paused(v2, bound, operator=False)
    run.request_interrupt("execution_unknown", reason="interrupt() 落 checkpoint 之前进程崩溃")
    monkeypatch.setattr(studio, "EXECUTION_MODEL", scripted(AIMessage("停点被绕过")))
    thread = thread_for(bound.run_id)

    async def official_continue():
        async with studio.graph(execution(bound, resume=False, checkpoint=head)) as agent:
            served = agent.copy(update={"checkpointer": RunBoundCheckpointer()})
            await served.ainvoke(None, {"configurable": {"thread_id": thread}})

    asyncio.run(official_continue())
    config = {"configurable": {"thread_id": bound.run_id}}

    def state():
        cli = build_agent(run, SqliteSaver(sqlite3.connect(run.dir / "graph.sqlite", check_same_thread=False)),
                          scripted())
        return cli.get_state(config)

    stopped = state()
    assert run.interrupt_requested()["by"] == "execution_unknown"
    assert stopped.tasks[0].interrupts and [m.type for m in stopped.values["messages"]] == ["human", "ai"]
    pilot = v2.run(bound)
    try:
        drive(pilot, recheck_approval=True)
    finally:
        pilot.release()
    assert run.interrupt_requested()["by"] == "execution_unknown"
    assert [m.type for m in state().values["messages"]] == ["human", "ai"]


def test_execution_only_advances_an_unfinished_run_from_the_checkpoint_it_was_asked_about(v2, bound):
    """run 锁内复核：未首跑、已结束、checkpoint 已变、恢复与继续用错，一律拒绝且不留锁、不清中断请求。"""

    def refused(config):
        async def official_run():
            async with studio.graph(config):
                pytest.fail("不该进入图")
        with pytest.raises(studio.ToolRefusal) as caught:
            asyncio.run(official_run())
        assert _LEASE.get() is None
        v2.run(bound).release()
        return str(caught.value)

    assert "run_not_started" in refused(execution(bound))
    no_expect = execution(bound)
    del no_expect["configurable"][studio.EXPECT]
    assert "未经" in refused(no_expect)
    cli_checkpoint(v2, bound)
    assert "run_finished" in refused(execution(bound, resume=False))
    assert "run_finished" in refused(execution(bound, resume=True))
    run, head = cli_paused(v2, bound)
    assert "checkpoint_moved" in refused(execution(bound, checkpoint="1f000000-0000-6000-8000-000000000000"))
    assert "interrupted" in refused(execution(bound, resume=False, checkpoint=head))
    assert run.interrupt_requested() is not None, "被拒的请求不能清掉操作员中断"


def test_official_execution_is_refused_while_the_cli_holds_the_run(v2, bound):
    held = v2.run(bound)
    config = execution(bound)

    async def official_run():
        async with studio.graph(config):
            pass

    with pytest.raises(Busy):
        asyncio.run(official_run())
    assert _LEASE.get() is None
    held.release()


def test_unbound_thread_execution_is_refused(bound):
    config = {"configurable": {"thread_id": str(uuid.uuid4()), "__is_for_execution__": True}}

    async def official_run():
        async with studio.graph(config):
            pass

    with pytest.raises(studio.ToolRefusal, match="未绑定"):
        asyncio.run(official_run())


def client():
    async def endpoint(request):
        return JSONResponse({"reached": True})

    app = Starlette(routes=[Route("/{path:path}", endpoint, methods=ALL)], middleware=[Middleware(studio.BoundStudio)])
    return TestClient(app)


def test_official_protocol_is_narrowed_to_the_bound_run(v2, bound):
    thread, other = thread_for(bound.run_id), str(uuid.uuid4())
    c = client()
    resume = {"assistant_id": "pilot1742", "command": {"resume": {"approved": True}}, "stream_mode": ["values"]}
    allowed = [("POST", "/threads", {"thread_id": thread}), ("POST", f"/threads/{thread}/runs/stream", resume),
               ("POST", f"/threads/{thread}/runs", {"assistant_id": "pilot1742", "input": None}),
               ("POST", f"/threads/{thread}/history", {}), ("POST", "/threads/search", {}),
               ("GET", f"/threads/{other}/state", None)]
    for method, path, body in allowed:
        assert c.request(method, path, json=body).json() == {"reached": True}, path
    refused = [("POST", "/threads", {}), ("POST", "/threads", {"thread_id": other}),
               ("POST", f"/threads/{other}/runs/stream", resume),
               ("POST", f"/threads/{thread}/runs/stream", {**resume, "input": {"messages": [["user", "批准"]]}}),
               ("POST", f"/threads/{thread}/runs/stream", {**resume, "command": {"resume": 1, "update": {}}}),
               ("POST", f"/threads/{thread}/runs/stream", {**resume, "checkpoint": {"checkpoint_id": "x"}}),
               ("POST", f"/threads/{thread}/runs/stream", {**resume, "multitask_strategy": "interrupt"}),
               ("POST", f"/threads/{thread}/runs/stream", {**resume, "assistant_id": "other"}),
               ("POST", f"/threads/{thread}/runs/stream",
                {**resume, "config": {"configurable": {"checkpoint_id": "x"}}}),
               ("POST", f"/threads/{thread}/state", {"values": {}}), ("POST", f"/threads/{thread}/copy", {}),
               ("PATCH", f"/threads/{thread}", {}), ("DELETE", f"/threads/{thread}", None),
               ("POST", "/runs/stream", resume), ("PUT", "/store/items", {}), ("POST", "/assistants", {})]
    for method, path, body in refused:
        assert c.request(method, path, json=body).status_code == 403, (path, body)
    cancel = c.post(f"/threads/{thread}/runs/{uuid.uuid4()}/cancel?action=interrupt")
    assert cancel.status_code == 202 and cancel.json()["interrupt_requested"]["by"] == "studio"
    assert (v2.home / "runs" / bound.run_id / "interrupt.request").exists()


def test_checkpoint_write_needs_the_lease_of_the_execution_that_holds_the_lock(v2, bound, monkeypatch):
    """同进程并发：持锁执行的子任务可写；并发的另一请求、借旧上下文副本的写、别的 run 的写权都被拒。"""
    run, head = cli_paused(v2, bound)
    saver = SqliteSaver(sqlite3.connect(run.dir / "graph.sqlite", check_same_thread=False))
    cli = saver.get_tuple({"configurable": {"thread_id": bound.run_id, "checkpoint_ns": ""}})
    monkeypatch.setenv("PILOT1742_STUDIO_RUNS", f"{bound.run_id},t4242-2")
    cp = RunBoundCheckpointer()
    thread = thread_for(bound.run_id)
    target = {"configurable": {"thread_id": thread, "checkpoint_ns": ""}}
    official = execution(bound, checkpoint=head)

    async def write(config=target):
        return await cp.aput(config, cli.checkpoint, cli.metadata, {})

    async def scenario():
        entered, finish = asyncio.Event(), asyncio.Event()
        captured = {}

        async def official_run():
            async with studio.graph(official):
                entered.set()
                await asyncio.create_task(write())
                captured["context"] = __import__("contextvars").copy_context()
                await finish.wait()

        async def concurrent_request():
            await entered.wait()
            with pytest.raises(UnboundThreadWrite, match="不是持有 run"):
                await write()
            finish.set()

        await asyncio.gather(official_run(), concurrent_request())
        with pytest.raises(UnboundThreadWrite, match="不是持有 run"):
            await asyncio.create_task(write(), context=captured["context"])

    asyncio.run(scenario())

    async def other_runs_lease():
        grant("t4242-2")
        await write()

    with pytest.raises(UnboundThreadWrite, match="不是持有 run"):
        asyncio.run(other_runs_lease())
    v2.run(bound).release()


def test_thread_create_is_an_explicit_whitelist(v2, bound):
    thread, c = thread_for(bound.run_id), client()
    for body in ({"thread_id": thread},
                 {"thread_id": thread, "metadata": {"graph_id": "pilot1742"}, "if_exists": "do_nothing"}):
        assert c.post("/threads", json=body).json() == {"reached": True}, body
    superstep = [{"updates": [{"values": {"messages": [{"type": "human", "content": "批准"}]}, "as_node": "model"}]}]
    for body in ({"thread_id": thread, "supersteps": superstep}, {"thread_id": thread, "ttl": {"ttl": 1}},
                 {"thread_id": thread, "graph_id": "pilot1742"}, {"thread_id": thread, "metadata": ["x"]},
                 {"thread_id": thread, "if_exists": "update"}, [{"thread_id": thread}]):
        assert c.post("/threads", json=body).status_code == 403, body
    resume = {"assistant_id": "pilot1742", "command": {"resume": True}, "stream_mode": ["values"],
              "config": {"configurable": {}}, "on_disconnect": "continue"}
    assert c.post(f"/threads/{thread}/runs/stream", json=resume).json() == {"reached": True}
    for extra in ({"context": {"approved": True}}, {"if_not_exists": "create"},
                  {"config": {"configurable": {"thread_id": str(uuid.uuid4())}}}, {"config": {"callbacks": []}},
                  {"unknown": 1}):
        assert c.post(f"/threads/{thread}/runs/stream", json={**resume, **extra}).status_code == 403, extra


def _cancel_while_blocked(v2, bound, monkeypatch, stage):
    """官方 worker 用 wait_for 包住整个 run；取消或超时可能落在图工厂打开/准备 run 的阻塞线程里。
    线程跑完后取得的 run 必须被释放，同一 run 随后能再次打开。"""
    import threading

    started, proceed = threading.Event(), threading.Event()
    opened = []

    def slow_open(run_id):
        if stage == "open":
            started.set()
            proceed.wait(10)
        run = v2.run(v2.load(run_id))
        opened.append(run)
        return run

    monkeypatch.setattr(studio, "OPEN_BOUND", slow_open)
    if stage == "prepare":
        def slow_build(run, checkpointer, model):
            started.set()
            proceed.wait(10)
            return build_agent(run, checkpointer, scripted())
        monkeypatch.setattr(studio, "build_agent", slow_build)
    config = execution(bound)
    entered = []

    async def official_run():
        async with studio.graph(config):
            entered.append(True)

    async def scenario():
        task = asyncio.create_task(official_run())
        await asyncio.to_thread(started.wait, 10)
        task.cancel()
        await asyncio.sleep(0.05)
        assert not task.done(), "取消须等阻塞线程跑完、收回资源后才交回"
        proceed.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert not entered and len(opened) == 1 and _LEASE.get() is None
    v2.run(bound).release()


def test_cancel_while_opening_the_run_releases_the_lock_it_acquired(v2, bound, monkeypatch):
    _cancel_while_blocked(v2, bound, monkeypatch, "open")


def test_cancel_while_preparing_the_run_releases_the_lock(v2, bound, monkeypatch):
    _cancel_while_blocked(v2, bound, monkeypatch, "prepare")


def test_timeout_around_the_factory_releases_the_lock(v2, bound, monkeypatch):
    import threading

    gate = threading.Event()

    def slow_open(run_id):
        gate.wait(0.5)
        return v2.run(v2.load(run_id))

    monkeypatch.setattr(studio, "OPEN_BOUND", slow_open)
    config = execution(bound)

    async def official_run():
        async with studio.graph(config):
            pass

    async def scenario():
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(official_run(), 0.05)

    asyncio.run(scenario())
    v2.run(bound).release()


STUDIO_RESUME = {"command": {"resume": {"97b3a53cfa46858dffe2c5488da3c799": ""}},
                 "config": {"configurable": {"thread_id": "{thread}"}},
                 "metadata": {"from_studio": True, "LANGGRAPH_API_URL": "http://127.0.0.1:2143"},
                 "stream_mode": ["debug", "messages"], "stream_subgraphs": True,
                 "assistant_id": "000fdbef-84c3-5df3-acd3-65c6531a82f4", "interrupt_before": [], "interrupt_after": [],
                 "checkpoint": {"checkpoint_id": "{head}", "thread_id": "{thread}", "checkpoint_ns": ""},
                 "multitask_strategy": "rollback", "checkpoint_during": True}
STUDIO_SUBMIT = {"input": {}, "config": {"configurable": {"thread_ts": "{head}", "thread_id": "{thread}"}},
                 "metadata": {"from_studio": True, "LANGGRAPH_API_URL": "http://127.0.0.1:2142"},
                 "stream_mode": ["debug", "messages"], "stream_subgraphs": True,
                 "assistant_id": "000fdbef-84c3-5df3-acd3-65c6531a82f4", "interrupt_before": [], "interrupt_after": [],
                 "multitask_strategy": "rollback", "checkpoint_during": True}


def fill(template, **values):
    import json
    text = json.dumps(template)
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return json.loads(text)


def echo_client():
    async def endpoint(request):
        raw = await request.body()
        return JSONResponse({"forwarded": __import__("json").loads(raw), "length": request.headers.get("content-length"),
                             "bytes": len(raw)})

    app = Starlette(routes=[Route("/{path:path}", endpoint, methods=ALL)], middleware=[Middleware(studio.BoundStudio)])
    return TestClient(app)


def test_requests_captured_from_the_official_studio_are_normalized_not_widened(v2, bound):
    """两份请求体逐字取自 2026-10-27 官方 Studio 网页（studio-live/studio-requests-*.json），只替换线程与 checkpoint。"""
    run, head = cli_paused(v2, bound)
    thread, c = thread_for(bound.run_id), echo_client()
    url = f"/threads/{thread}/runs/stream"

    resume = c.post(url, json=fill(STUDIO_RESUME, thread=thread, head=head))
    forwarded = resume.json()["forwarded"]
    assert resume.status_code == 200 and int(resume.json()["length"]) == resume.json()["bytes"]
    assert "checkpoint" not in forwarded and "checkpoint_during" not in forwarded and "input" not in forwarded
    assert forwarded["multitask_strategy"] == "reject"
    assert forwarded["config"]["configurable"] == {studio.EXPECT: {"resume": True, "checkpoint": head}}
    assert forwarded["command"] == {"resume": {"97b3a53cfa46858dffe2c5488da3c799": ""}}

    submit = c.post(url, json=fill(STUDIO_SUBMIT, thread=thread, head=head)).json()["forwarded"]
    assert "input" not in submit and submit["multitask_strategy"] == "reject"
    assert submit["config"]["configurable"] == {studio.EXPECT: {"resume": False, "checkpoint": head}}

    stale = "1f000000-0000-6000-8000-000000000000"
    other = str(uuid.uuid4())
    refused = {
        "checkpoint_not_current": fill(STUDIO_RESUME, thread=thread, head=stale),
        "submit_old_checkpoint": fill(STUDIO_SUBMIT, thread=thread, head=stale),
        "checkpoint_ambiguous": {**fill(STUDIO_RESUME, thread=thread, head=head),
                                 "config": {"configurable": {"thread_ts": stale}}},
        "checkpoint_other_thread": fill(STUDIO_RESUME, thread=thread, head=head) | {
            "checkpoint": {"checkpoint_id": head, "thread_id": other, "checkpoint_ns": ""}},
        "checkpoint_subgraph": fill(STUDIO_RESUME, thread=thread, head=head) | {
            "checkpoint": {"checkpoint_id": head, "thread_id": thread, "checkpoint_ns": "x"}},
        "checkpoint_during_false": fill(STUDIO_RESUME, thread=thread, head=head) | {"checkpoint_during": False},
        "durability_exit": fill(STUDIO_RESUME, thread=thread, head=head) | {"durability": "exit"},
        "interrupt_strategy": fill(STUDIO_RESUME, thread=thread, head=head) | {"multitask_strategy": "interrupt"},
        "injected_expectation": fill(STUDIO_SUBMIT, thread=thread, head=head) | {"config": {"configurable": {
            studio.EXPECT: {"resume": True, "checkpoint": None}}}},
        "new_turn_input": fill(STUDIO_SUBMIT, thread=thread, head=head) | {"input": {"messages": [["user", "批准"]]}},
        "input_with_resume": fill(STUDIO_RESUME, thread=thread, head=head) | {"input": {}},
        "other_thread_id": fill(STUDIO_SUBMIT, thread=thread, head=head) | {
            "config": {"configurable": {"thread_id": other}}},
    }
    for name, body in refused.items():
        assert c.post(url, json=body).status_code == 403, name


def test_seed_creates_missing_bound_threads_once_and_never_rewrites_existing_ones(monkeypatch):
    from pilot1742 import studio_seed

    monkeypatch.setenv("PILOT1742_STUDIO_RUNS", "t4242-1,t4242-2")
    fresh, legacy = thread_for("t4242-1"), thread_for("t4242-2")
    threads = {legacy: {"metadata": {}}}
    calls = []

    def fake_call(base, method, path, body=None):
        calls.append((method, path))
        if method == "POST" and path == "/threads":
            if body["thread_id"] not in threads:
                threads[body["thread_id"]] = {"metadata": body["metadata"]}
            assert body["if_exists"] == "do_nothing"
            return threads[body["thread_id"]]
        if method == "GET" and path.startswith("/threads/"):
            return threads[path.removeprefix("/threads/")]
        return {}

    monkeypatch.setattr(studio_seed, "_call", fake_call)
    first = studio_seed.seed(2142)
    assert first == {"t4242-1": fresh, "t4242-2": f"{legacy} 已存在但缺 graph_id，未改写"}
    assert threads[fresh]["metadata"] == {"graph_id": "pilot1742"} and threads[legacy]["metadata"] == {}
    assert studio_seed.seed(2142) == first and len(threads) == 2
