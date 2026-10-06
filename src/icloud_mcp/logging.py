"""Only fixed codes and tool names are logged; never log arguments or exceptions."""
import json
import sys


def log(tool, code, request_id):
    print(json.dumps({"tool": tool, "code": code, "request_id": request_id}), file=sys.stderr, flush=True)
