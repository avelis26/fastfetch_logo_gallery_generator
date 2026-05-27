#!/usr/bin/env python3
import argparse
import re
import sys
from pathlib import Path

CONFIG_PATH = Path.home() / ".config/fastfetch/config.jsonc"


def main():
    parser = argparse.ArgumentParser(description="Change the fastfetch logo source.")
    parser.add_argument("--source", required=True, help="Logo source to set (e.g. cachyos)")
    args = parser.parse_args()

    if not CONFIG_PATH.exists():
        print(f"Error: config file not found at {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)

    raw = CONFIG_PATH.read_text(encoding="utf-8")

    new_raw, n = re.subn(
        r'("source"\s*:\s*)"[^"]*"',
        rf'\1"{args.source}"',
        raw,
        count=1
    )

    if n == 0:
        print("Error: could not locate 'source' field to replace.", file=sys.stderr)
        sys.exit(1)

    CONFIG_PATH.write_text(new_raw, encoding="utf-8")
    print(f"Updated logo source → \"{args.source}\"")


if __name__ == "__main__":
    main()
