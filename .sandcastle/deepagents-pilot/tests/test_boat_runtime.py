import json
import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import MODELS, Env, git
from test_boat import adapter

from pilot1742.domain import DEEPAGENTS_OUTPUT_PROTOCOL, parse_sha

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ("boat-worker.mts", "codex-child.ts", "docker-isolation.mts", "acceptance-dir.mts",
           "git-environment.ts", "main-model.mts")


@pytest.fixture(scope="module")
def _runtime_seeds(tmp_path_factory):
    root = tmp_path_factory.mktemp("boat_runtime_seeds")
    pstack = root / "pstack"
    skill = pstack / "installed/skills/a/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("fixture")
    (pstack / "aliases.json").write_text("{}")
    (pstack / "upstream").mkdir()
    (pstack / "upstream/LICENSE").write_text("fixture")
    rules = root / "models.md"
    rules.write_text("fixture")

    seeds = {}
    for scheduler, missing_record in ((False, False), (True, False), (True, True)):
        case_dir = root / f"s{int(scheduler)}_m{int(missing_record)}"
        case_dir.mkdir()
        seed_env = Env(case_dir)
        paths = ["package.json", "package-lock.json", ".sandcastle/deepagents-pilot/pilot1742/boat_remote.py"]
        paths.extend(".sandcastle/" + name for name in RUNTIME)
        if scheduler:
            paths.extend((".sandcastle/scheduler-config.mts", ".sandcastle/scheduler-config.json"))
        for name in paths:
            target = seed_env.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes() if scheduler or not name.endswith((".mts", ".ts"))
                               else b"export {};\n")
        if missing_record:
            (seed_env.source / ".sandcastle/scheduler-config.json").unlink()
        project_skill = seed_env.source / ".agents/skills/fixture/SKILL.md"
        project_skill.parent.mkdir(parents=True)
        project_skill.write_text("fixture")
        git(seed_env.source, "add", ".")
        git(seed_env.source, "commit", "-qm", "frozen runtime")
        base = parse_sha(git(seed_env.source, "rev-parse", "HEAD"))
        if scheduler:
            (seed_env.source / ".sandcastle/scheduler-config.json").write_text("{}")
        else:
            (seed_env.source / ".sandcastle/scheduler-config.mts").write_text("throw new Error('not frozen');")
        expected_runtime = {
            name: git(seed_env.source, "show", f"{base}:.sandcastle/{name}") + "\n"
            for name in RUNTIME
        }
        expected_scheduler = (
            json.loads(git(seed_env.source, "show", f"{base}:.sandcastle/scheduler-config.json"))
            if scheduler and not missing_record
            else None
        )
        seeds[(scheduler, missing_record)] = (seed_env.source, base, expected_runtime, expected_scheduler)
    return pstack, rules, seeds


@pytest.mark.parametrize("model", ["gpt-6.1-sol", "kimi-k3.1-pro"])
@pytest.mark.parametrize("protocol", [None, DEEPAGENTS_OUTPUT_PROTOCOL])
@pytest.mark.parametrize(("scheduler", "missing_record"), [(False, False), (True, False), (True, True)])
def test_frozen_runtime_package_keeps_its_import_closure(_runtime_seeds, tmp_path, scheduler, missing_record, protocol, model):
    pstack, rules, seeds = _runtime_seeds
    seed_source, base, expected_runtime, expected_scheduler = seeds[(scheduler, missing_record)]
    env = Env.__new__(Env)
    env.home = tmp_path / "home"
    env.home.mkdir()
    env.source = tmp_path / "source"
    shutil.copytree(seed_source, env.source)
    env.base = base
    env.control({})
    run, engine, key, binding = adapter(env, models=MODELS.replace("gpt-6.1-sol", model))
    engine.config = replace(engine.config, pstack_source=str(pstack), model_rules=str(rules))
    prompt = run.dir / "prompt.md"
    prompt.write_text("fixture")
    intent = run.dir / "intents" / f"{key.name}.json"
    intent.parent.mkdir(exist_ok=True)
    intent.write_text(json.dumps({"prompt_file": str(prompt), "model": str(run.spec.author_model), "mode": "execute",
                                  **({"output_protocol": protocol} if protocol else {})}))
    try:
        if missing_record:
            with pytest.raises(subprocess.CalledProcessError):
                engine._build(key, binding)
            assert not (run.dir / "boat/packages" / binding.package_id).exists()
            assert engine.cli.calls == []
            return
        package = engine._build(key, binding)
        request = json.loads((package / "request.json").read_text())
        assert request["model"] == model
        assert request.get("output_protocol") == protocol
        assert request["prompt"] == "fixture"
        runtime = package / "runtime/.sandcastle"
        for name in RUNTIME:
            assert (runtime / name).read_text() == expected_runtime[name]
        for module in runtime.iterdir():
            if module.suffix not in (".ts", ".mts"):
                continue
            for imported in re.findall(r'(?:from|import)\s*["\'](\./[^"\']+)["\']', module.read_text()):
                assert (runtime / imported).is_file(), (module.name, imported)
        if scheduler:
            result = subprocess.run(
                ["node", "--experimental-strip-types", "--input-type=module", "-e",
                 'import {readSchedulerConfig} from "./scheduler-config.mts";'
                 'console.log(JSON.stringify(readSchedulerConfig(undefined, {}).values));'],
                cwd=runtime, capture_output=True, text=True, timeout=10)
            assert result.returncode == 0, result.stderr
            assert json.loads(result.stdout) == expected_scheduler["values"]
        else:
            assert not (runtime / "scheduler-config.mts").exists()
            assert not (runtime / "scheduler-config.json").exists()
        assert engine.cli.calls == []
        assert engine._build(key, binding) == package
    finally:
        run.release()
