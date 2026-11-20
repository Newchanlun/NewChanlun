from pathlib import Path
import sys, subprocess
base = Path(__file__).parent
log = Path("/Users/silencehan/.t3/evidence/issue1418-at14-report/non-author-astra-2d77870e/boat.log")
cmd = ["boat","run","--no-env","--timeout","660","--push",str(base/"boat-input"),"--","bash","run.sh"]
with log.open("x",buffering=1) as out:
    with subprocess.Popen(cmd, stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1) as p:
        for line in p.stdout:
            out.write(line)
            print(line, end="", flush=True)
        rc = p.wait()
    out.write(f"boat_cli_exit={rc}\n")
sys.exit(rc)
