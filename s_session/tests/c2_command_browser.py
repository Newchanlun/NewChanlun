"""以临时 Firefox 配置操作既有 economic.html；只与同一轮 E socket 的写回执比较。"""
import argparse
import base64
import json
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def check_page(js, screenshot, run, output):
    def settle():
        deadline = time.monotonic() + 36
        while time.monotonic() < deadline:
            status = js("const s=document.querySelector('#status'); return [s.textContent,"
                        "s.classList.contains('error'),s.hasAttribute('aria-busy')]")
            assert not status[1], status[0]
            if not status[2] and "各域已核对" in status[0]:
                return
            time.sleep(.08)
        raise TimeoutError(status[0])

    def receipt(name):
        return json.loads((run / (name + ".reply.wire")).read_bytes())["payload"]

    settle()
    assert js("return document.querySelector('#time-label').textContent") == "当时可知 bar"
    dispatch, release = receipt("MakeDispatchable-alpha"), receipt("ReleaseExact-alpha")
    button = "document.querySelector('button[data-original-kind=command][data-original-id=cmd-alpha]')"
    checked = []
    for expected, receipts in [(dispatch, [dispatch]), (release, [dispatch, release])]:
        if len(receipts) == 1:
            js("document.querySelector('#known-at').value='1';document.querySelector('#as-known').click()")
        else:
            js("document.querySelector('#watch').click()")
        settle()
        cut = expected["cut"]
        assert f"E · 提交 {cut['commit_seq']} · {cut['root_hash']}" in js("return document.querySelector('#cuts').textContent")
        assert js("return "+button+".parentElement.querySelector('h4').textContent") == "cmd-alpha · "+expected["record"]["state"]
        js(button+".scrollIntoView({block:'center'});"+button+".click()")
        deadline = time.monotonic() + 30
        while js("return "+button+".disabled"):
            if time.monotonic() >= deadline:
                raise TimeoutError("命令原件未返回")
            time.sleep(.1)
        raw = js("return "+button+".nextElementSibling.textContent")
        reply = json.loads(raw)
        assert reply["cuts"]["E"] == cut
        assert reply["original"] == dict(kind="EconomicCommand", command_id="cmd-alpha", domain_id="E",
                                         cut=cut, state=expected["record"]["state"], record=expected["record"],
                                         receipts=receipts)
        kinds = "、".join(r["kind"] for r in receipts)
        assert f"E 提交 {cut['commit_seq']} · {len(receipts)} 份原回执：{kinds}" in js("return "+button+".parentElement.innerText")
        if len(receipts) == 2:
            assert "首次量 2 · 分配 alloc-alpha · 放行读数 2" in js("return "+button+".parentElement.innerText")
        (output / f"cut-{cut['commit_seq']}.json").write_text(raw)
        (output / f"cut-{cut['commit_seq']}.png").write_bytes(screenshot())
        checked.append(dict(cut=cut, state=expected["record"]["state"], receipts=[r["receipt_key"] for r in receipts]))
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geckodriver", required=True)
    parser.add_argument("--profile-root", type=Path, help="Firefox 与 WebDriver 共享的临时配置父目录")
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    output = args.run / "browser"
    output.mkdir()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    def driver(method, route, data=None):
        req = Request(f"http://127.0.0.1:{port}"+route, method=method,
                      data=None if data is None else json.dumps(data).encode(),
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=40) as response:
                return json.load(response)["value"]
        except HTTPError as exc:
            raise RuntimeError(exc.read().decode()) from exc

    with tempfile.TemporaryDirectory(prefix="c2-1407-", dir=args.profile_root) as tmp, (output / "geckodriver.log").open("w") as log:
        process = subprocess.Popen([args.geckodriver, "--host", "127.0.0.1", "--port", str(port), "--profile-root", tmp],
                                   stdout=log, stderr=subprocess.STDOUT)
        sid = None
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    if driver("GET", "/status")["ready"]:
                        break
                except OSError:
                    time.sleep(.1)
            options = {"args":["-headless"], "prefs":{"network.proxy.type":0, "app.update.auto":False}}
            browser = driver("POST", "/session", {"capabilities":{"alwaysMatch":{"browserName":"firefox","moz:firefoxOptions":options}}})
            sid = "/session/"+browser["sessionId"]
            driver("POST", sid+"/url", {"url":f"http://127.0.0.1:{args.port}/economic.html"})
            checked = check_page(lambda code: driver("POST", sid+"/execute/sync", {"script":code,"args":[]}),
                                 lambda: base64.b64decode(driver("GET",sid+"/screenshot")), args.run, output)
            result = dict(browser="Firefox "+browser["capabilities"]["browserVersion"], cuts=checked)
            (output / "result.json").write_text(json.dumps(result, indent=2))
            print(json.dumps(result), flush=True)
        finally:
            try:
                if sid:
                    driver("DELETE", sid)
            finally:
                process.terminate()
                process.wait(10)


if __name__ == "__main__":
    main()
