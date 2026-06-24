import sys
import json


def main() -> None:
    """Read JSON-RPC requests from stdin and echo them back to stdout."""
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
            if "id" in msg:
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg["id"],
                    "result": msg.get("params"),
                }
                print(json.dumps(resp))
                sys.stdout.flush()
        except Exception as e:
            sys.stderr.write(f"Error: {e}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    main()
