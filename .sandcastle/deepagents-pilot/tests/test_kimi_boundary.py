"""#1742/#1911：Kimi 的真实调用代码配离线传输/沙盒替身。"""
import json
import subprocess
from functools import partial
from pathlib import Path

import httpx

from pilot1742 import agent
from pilot1742.domain import MODEL_FAMILY
from pilot1742.run import plan_roles

ROOT = Path(__file__).resolve().parents[3]
PROJECT_RULES = ROOT / '.sandcastle/deepagents-pilot/pstack-models.md'


def test_project_roles_and_chat_openai_tool_wire(monkeypatch):
    plan = plan_roles(PROJECT_RULES.read_text())
    assert (plan.author, plan.brain, *plan.design, plan.reviewer, plan.judge) == (
        'kimi-k3.1-pro', 'kimi-k3.1-pro', 'kimi-k3.1-pro', 'claude-opus-5-5',
        'claude-opus-5-5', 'claude-opus-5-5')
    assert MODEL_FAMILY[plan.brain] == 'moonshot'
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            'id': 'fixture', 'object': 'chat.completion', 'created': 0, 'model': plan.brain,
            'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {
                'role': 'assistant', 'content': None, 'tool_calls': [{
                    'id': 'fixture-call', 'type': 'function',
                    'function': {'name': 'run_status', 'arguments': '{}'}}]}}]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(agent, 'ChatOpenAI', partial(agent.ChatOpenAI, http_client=client))
        model = agent.build_model(plan.brain).bind_tools([{
            'type': 'function', 'function': {'name': 'run_status', 'description': '只读状态',
                                           'parameters': {'type': 'object', 'properties': {}}}}])
        reply = model.invoke('读取状态')
    assert reply.tool_calls[0]['name'] == 'run_status'
    assert len(requests) == 1
    assert str(requests[0].url) == agent.CLIPROXY_BASE_URL + '/chat/completions'
    body = json.loads(requests[0].content)
    assert body['model'] == 'kimi-k3.1-pro'
    assert body['reasoning_effort'] == agent.BRAIN_EFFORT
    assert body['max_completion_tokens'] == agent.BRAIN_MAX_TOKENS
    assert body['tools'][0]['function']['name'] == 'run_status'


def test_actual_boat_worker_passes_kimi_to_sandcastle(tmp_path):
    root = tmp_path / 'package'
    (root / 'claim').mkdir(parents=True)
    (root.parent / 'private').mkdir()
    (root.parent / 'private/model-key').write_text('fixture-only')
    captured = tmp_path / 'captured.json'
    request = dict(root=str(root), model='kimi-k3.1-pro', mode='execute', ticket=1911,
                   image='sha256:' + 'a' * 64, endpoint='https://fixture.invalid/v1',
                   identity={'run_id': 't1911-1', 'target_head': 'b' * 40})
    path = root / 'request.json'
    path.write_text(json.dumps(request))
    # 导入钩子只替换外部沙盒边界；执行仓内原始 boat-worker.mts。
    modules = {
        '@ai-hero/sandcastle': (
            'import {writeFileSync} from "node:fs"; export function codex(model, options) {'
            f'writeFileSync({json.dumps(str(captured))}, JSON.stringify({{model, options}}));'
            'throw new Error("fixture-stop-before-model");}'),
        '@ai-hero/sandcastle/sandboxes/docker': (
            'export function docker() {return {create: async () => ({'
            'copyFileIn: async () => {}, close: async () => {}})}}'),
        './codex-child.ts': (
            'export class CodexTranscript {}'
            'export const outputProtocol = x => x; export const workerOutputSchema = () => ({});'
            'export const PROVIDER_DEFINITION = {};'
            'export const snapshotCheckout = () => ({head: "' + 'b' * 40 + '", status: ""});'),
        './docker-isolation.mts': (
            'export const assertContainerIsolationContract = () => ({});'
            'export const hardenProvider = x => x;'),
    }
    loader = tmp_path / 'loader.mjs'
    loader.write_text('import {registerHooks} from "node:module";\n'
                      f'const modules = {json.dumps(modules)};\n'
                      'registerHooks({resolve(s, c, next) {return s in modules ? '
                      '{url: "data:text/javascript," + encodeURIComponent(modules[s]), shortCircuit: true}'
                      ': next(s, c)}});\n')
    result = subprocess.run(['node', '--experimental-strip-types', '--import', str(loader),
                             str(ROOT / '.sandcastle/boat-worker.mts'), str(path)],
                            capture_output=True, text=True, timeout=15)
    assert captured.exists(), result.stderr
    invocation = json.loads(captured.read_text())
    assert invocation['model'] == 'kimi-k3.1-pro'
    assert invocation['options']['effort'] == 'high'
    assert 'fixture-stop-before-model' in (root / 'claim/receipt.json').read_text()
