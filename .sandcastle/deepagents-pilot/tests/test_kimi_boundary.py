"""#1742/#1911：Kimi 的真实调用代码配离线传输/沙盒替身。"""
import json
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
