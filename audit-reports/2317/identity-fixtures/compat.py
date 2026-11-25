"""提交身份正向对照、工作区必红样本和 Git 调用环境。所有写入仅发生在 TMPDIR。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture_repo import A, B, CHECK, G, first, gate, git, run, seed, tmp_parent

tmp = Path(tempfile.mkdtemp(dir=tmp_parent()))
repo = tmp/"base"
seed(Path.cwd(), repo)
script = repo/CHECK


def case(label, root, code, detail, *args, env=None):
    p = gate(script, root, *args, env=env)
    message = first(p)
    print(label, p.returncode, message, flush=True)
    assert p.returncode == code and detail in message, label


case("基线", repo, 0, "GREEN")
git(repo, "tag", "-a", "approved", "-m", "核对带注标签")
case("带注标签", repo, 0, "GREEN", "--rev", "approved")
case("不存在的对象", repo, 2, "无法运行", "--rev", "no-such-rev")
for typ, expr in (("tree","HEAD^{tree}"), ("blob","HEAD:"+A+"/SPEC.md")):
    oid = git(repo, "rev-parse", expr).decode().strip()
    assert git(repo, "cat-file", "-t", oid).decode().strip() == typ
    case(typ+" 对象号", repo, 2, "无法运行", "--rev", oid)
case("非仓库根", tmp, 2, "无法运行")
bare = tmp/"bare"
git(tmp, "clone", "-q", "--shared", "--bare", str(repo), str(bare))
policy = run(repo, "git", "config", "--get", "safe.bareRepository", check=False).stdout.strip()
if policy == b"explicit":
    case("裸仓库(只传 root，宿主要求显式 git-dir)", bare, 2, "无法运行", "--no-worktree")
case("裸仓库(显式 git-dir 和只核提交)", bare, 0, "GREEN", "--no-worktree", env={"GIT_DIR":str(bare)})
case("裸仓库(默认核磁盘)", bare, 1, "缺文件", env={"GIT_DIR":str(bare)})
case("有效 GIT_DIR", repo, 0, "GREEN", env={"GIT_DIR":str(repo/".git")})
case("无效 GIT_DIR", repo, 2, "无法运行", env={"GIT_DIR":str(tmp/"absent")})
case("显式 root；另设 GIT_WORK_TREE", repo, 0, "GREEN", env={"GIT_WORK_TREE":str(tmp)})
case("另设 GIT_INDEX_FILE", repo, 0, "GREEN", env={"GIT_INDEX_FILE":str(tmp/"index")})
case("注入无关配置", repo, 0, "GREEN", env={"GIT_CONFIG_COUNT":"1", "GIT_CONFIG_KEY_0":"core.quotePath",
                                            "GIT_CONFIG_VALUE_0":"false"})
case("追加正常对象目录", repo, 0, "GREEN", env={"GIT_ALTERNATE_OBJECT_DIRECTORIES":str(bare/"objects")})

for branch in ("left", "right"):
    git(repo, "checkout", "-qb", branch, "approved")
    (repo/branch).write_text(branch)
    git(repo, "add", "--", branch)
    git(repo, "commit", "-qm", branch)
git(repo, "merge", "--no-ff", "-qm", "合并对照", "left")
assert len(git(repo, "show", "-s", "--format=%P").split()) == 2
case("双亲合并提交", repo, 0, "GREEN")
shallow = tmp/"merge-shallow"
git(tmp, "clone", "-q", "--depth=1", repo.as_uri(), str(shallow))
assert git(shallow, "rev-parse", "--is-shallow-repository").strip() == b"true"
assert git(shallow, "rev-list", "--count", "HEAD").strip() == b"1"
assert git(shallow, "cat-file", "-p", "HEAD").count(b"\nparent ") == 2
case("双亲合并提交 depth=1", shallow, 0, "GREEN")
(repo/".git/info/grafts").write_bytes(git(repo,"rev-parse","HEAD"))
case("旧式嫁接只截断父历史", repo, 0, "GREEN")

t = A+"/SPEC.md"
saved = (repo/t).read_bytes()
for setbit, clearbit in (("--assume-unchanged","--no-assume-unchanged"),("--skip-worktree","--no-skip-worktree")):
    git(repo, "update-index", setbit, "--", t)
    case(setbit+" 原样", repo, 0, "GREEN")
    (repo/t).write_bytes(saved+b"\n")
    case(setbit+" 内容不同", repo, 1, "工作区内容与提交不同")
    (repo/t).write_bytes(saved)
    git(repo, "update-index", clearbit, "--", t)
git(shallow, "sparse-checkout", "set", A, B, G)
case("稀疏含两目录", shallow, 0, "GREEN")
git(shallow, "sparse-checkout", "set", A, G)
case("稀疏缺语料", shallow, 1, "缺文件")
case("稀疏仅核提交", shallow, 0, "GREEN", "--no-worktree")
(repo/A/".DS_Store").write_bytes(b"test")
case("未跟踪 .DS_Store", repo, 1, "工作区多出文件")
case("未跟踪物不进对象", repo, 0, "GREEN", "--no-worktree")

for loc in ("C", "en_US.UTF-8", "zh_CN.UTF-8"):
    cmd = run(repo/B, "bash", "-o", "pipefail", "-c", "sha256sum -- *.md | sha256sum", env={"LC_ALL":loc})
    digest = cmd.stdout.split()[0].decode()
    print("shell glob", loc, digest, flush=True)
    assert digest == "b6a35574ed6db3625da6d18f4e11c8976874ba66b0e888362e1769483f0c0a0d"
