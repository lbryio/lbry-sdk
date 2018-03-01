import os.path as op
import subprocess

try:
  import mkdocs
except ImportError:
  raise ImportError("mkdocs is not installed")

try:
  import tabulate
except ImportError:
  raise ImportError("tabulate is not installed")

try:
  import gen_cli_docs
  import gen_api_docs
except ImportError:
  raise ImportError("Probably not inside the lbry's virtual environment or daemon not installed")

gen_cli_docs.main()
gen_api_docs.main()
cwd = op.dirname(op.realpath(__file__))
cwd = op.realpath(op.join(cwd, ".."))
proc = subprocess.Popen("exec mkdocs build", cwd=cwd, shell=True)
proc.kill()
