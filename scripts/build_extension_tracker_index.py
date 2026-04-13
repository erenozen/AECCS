from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path


BIT_COUNT = 2_097_152
HASH_SEEDS = [2166136261, 1315423911, 2654435761, 2246822519, 3266489917]
RULE_PATTERN = re.compile(r"^\|\|([a-zA-Z0-9._-]+)\^")


def parse_adblock_domains(path: Path) -> list[str]:
    seen: set[str] = set()
    domains: list[str] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("!") or "##" in line or "#@#" in line:
            continue
        match = RULE_PATTERN.match(line)
        if not match:
            continue
        domain = match.group(1).lower()
        if domain in seen:
            continue
        seen.add(domain)
        domains.append(domain)

    return domains


def fnv1a_32(value: str, seed: int) -> int:
    h = seed & 0xFFFFFFFF
    for byte in value.encode("utf-8"):
        h ^= byte
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def build_bloom_filter(domains: list[str], bit_count: int, hash_seeds: list[int]) -> bytes:
    bitset = bytearray(bit_count // 8)
    for domain in domains:
        for seed in hash_seeds:
            position = fnv1a_32(domain, seed) % bit_count
            bitset[position >> 3] |= 1 << (position & 7)
    return bytes(bitset)


def build_payload(easyprivacy_path: Path, easylist_path: Path) -> dict:
    easyprivacy_domains = parse_adblock_domains(easyprivacy_path)
    easylist_domains = parse_adblock_domains(easylist_path)

    return {
        "metadata": {
            "sourceFiles": [easyprivacy_path.name, easylist_path.name],
            "bitCount": BIT_COUNT,
            "hashSeeds": HASH_SEEDS,
            "easyprivacyCount": len(easyprivacy_domains),
            "easylistCount": len(easylist_domains),
        },
        "easyprivacy": {
            "bitCount": BIT_COUNT,
            "hashSeeds": HASH_SEEDS,
            "base64": base64.b64encode(
                build_bloom_filter(easyprivacy_domains, BIT_COUNT, HASH_SEEDS)
            ).decode("ascii"),
        },
        "easylist": {
            "bitCount": BIT_COUNT,
            "hashSeeds": HASH_SEEDS,
            "base64": base64.b64encode(
                build_bloom_filter(easylist_domains, BIT_COUNT, HASH_SEEDS)
            ).decode("ascii"),
        },
    }


def render_js(payload: dict) -> str:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    return (
        "/*\n"
        " * Precompiled tracker-domain index for the AECCS browser extension.\n"
        " *\n"
        " * Generated from local EasyPrivacy and EasyList domain-only rules using\n"
        " * scripts/build_extension_tracker_index.py. This file is intentionally\n"
        " * static so the extension never parses large filter lists at runtime.\n"
        " */\n\n"
        f"const AECCSTrackerIndex = {body};\n\n"
        "if (typeof globalThis !== \"undefined\") {\n"
        "  globalThis.AECCSTrackerIndex = AECCSTrackerIndex;\n"
        "}\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the extension tracker bloom index.")
    parser.add_argument(
        "--easyprivacy",
        default="data/tracker_lists/easyprivacy.txt",
        help="Path to the EasyPrivacy rules file.",
    )
    parser.add_argument(
        "--easylist",
        default="data/tracker_lists/easylist.txt",
        help="Path to the EasyList rules file.",
    )
    parser.add_argument(
        "--output",
        default="extension/lib/tracker-index.js",
        help="Output JS file path.",
    )
    args = parser.parse_args()

    payload = build_payload(Path(args.easyprivacy), Path(args.easylist))
    output_path = Path(args.output)
    output_path.write_text(render_js(payload), encoding="utf-8")
    print(f"[OK] Wrote {output_path} ({output_path.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
