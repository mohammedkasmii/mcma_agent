"""Backward-compatible facade for the deterministic Wexia mapper."""

from __future__ import annotations

import argparse
import json

from mcma.mapping.wexia import WexiaDossierMapper


class WexiaToDossierMapper:
    """Compatibility wrapper used by older integrations.

    New code should depend on ``mcma.mapping.WexiaDossierMapper`` and its typed
    ``MappedDossier`` result directly.
    """

    def __init__(self, download_dir: str = "temp") -> None:
        self.download_dir = download_dir
        self._mapper = WexiaDossierMapper()

    def map(self, wexia: dict) -> dict:
        return self._mapper.map(wexia).to_public_dict()

    async def download_documents(self, documents: list) -> list:
        raise RuntimeError("GED and document downloading are disabled in the assisted-fill build")


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview the deterministic MCMA mapping")
    parser.add_argument("json_path")
    args = parser.parse_args()
    mapped = WexiaDossierMapper().from_file(args.json_path)
    print(json.dumps(mapped.to_public_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
