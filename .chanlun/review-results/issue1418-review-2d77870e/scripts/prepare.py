from pathlib import Path
import subprocess, tarfile
from io import BytesIO
root = Path("/Users/silencehan/.t3/tmp-work/review-1418")
out = Path(__file__).parent / "boat-input"
head = subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()
assert head == "2d77870e12b753cac4e79fa7d491e1821a09555f"
paths = ["rust/src","rust/tests","rust/Cargo.toml","rust/Cargo.lock","s_session/tests/issue1527_recovery","s_session/tests/issue1657_admission.rs"]
paths += ["s_session/tests/fixtures/"+n for n in ("tb02b","tb02c","tb02d")]
raw = subprocess.check_output(["git","archive","--format=tar",head,"--",*paths], cwd=root)
with tarfile.open(fileobj=BytesIO(raw)) as ar:
    ar.extractall(out,filter="data")
(out/"CANDIDATE").write_text(head+"\n")
src = (out/"rust/src/at14_report/tests.rs").read_text().splitlines()
# Reuse the candidate's unchanged synthetic sample as a consumer, without crate-private symbols.
imports = ["use newchan_rust::at14_report::*;", "use newchan_rust::lav_seal::{digest,jcs};"]
fixture = "\n".join(src[:3] + imports + src[9:37] + src[89:272]).replace("fn valid_pass_input()", "pub(super) fn valid_pass_input()")
(out/"review/src/fixture.rs").write_text(fixture+"\n")
(out/"review/Cargo.lock").write_bytes((out/"rust/Cargo.lock").read_bytes())
print(head, len(list(out.rglob("*"))),"paths")
