"""Send a Wexia dossier to the read-only planning API."""

import argparse
import json

import requests


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/v1/plan-dossier")
    args = parser.parse_args()

    with open(args.json, "r", encoding="utf-8") as source:
        payload = json.load(source)
    response = requests.post(args.url, json=payload, timeout=30)
    response.raise_for_status()
    print(json.dumps(response.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
