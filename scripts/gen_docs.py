import gen_cli_docs
import gen_api_docs
import os.path as op
import subprocess

gen_cli_docs.main()
gen_api_docs.main()
cwd = op.dirname(op.realpath(__file__))
cwd = op.realpath(op.join(cwd, ".."))
proc = subprocess.Popen("mkdocs build", cwd=cwd, shell=True)
