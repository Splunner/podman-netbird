#!/usr/bin/env python3
"""
setup_directories.py
Creates the required directory structure for the Podman / NetBird / Traefik stack.
Paths are read from a template_build config file (.env, .json, or .yaml).

Usage:
  python3 setup_directories.py --dry-run              # preview only
  python3 setup_directories.py                        # create directories
  python3 setup_directories.py --config my.env        # custom config file
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import stat
from pathlib import Path

# ── ANSI colors ───────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

OK      = f"{GREEN}[  OK  ]{RESET}"
FAIL    = f"{RED}[ FAIL ]{RESET}"
WARN    = f"{YELLOW}[ WARN ]{RESET}"
DRY     = f"{CYAN}[ DRY  ]{RESET}"
EXISTS  = f"{YELLOW}[EXISTS]{RESET}"
INFO    = f"{CYAN}[ INFO ]{RESET}"

# ── Default directory list (fallback if config file is missing) ───────────────
DEFAULT_DIRECTORIES: dict[str, str] = {
    "DIR_NETBIRD_SERVER":        "/opt/storage/netbird_server",
    "DIR_POSTGRES_DATA_NETBIRD": "/opt/storage/postgres_data_netbird",
    "DIR_POSTGRES_DATA":         "/opt/storage/postgres_data",
    "DIR_NETBIRD_LETSENCRYPT":   "/opt/storage/netbird_letsencrypt",
    "DIR_CONFIG_NETBIRD":        "/opt/configurations/netbird",
    "DIR_CONFIG_TRAEFIK":        "/opt/configurations/traefik",
    "DIR_CONFIG_KEYCLOAK":       "/opt/configurations/keyclaok",   # matches original typo
    "DIR_CONFIG_POSTGRES":       "/opt/configurations/postgres",
    "DIR_DB_MIGRATION":          "/opt/configuration/database_migration",
    # template builder directories
    "DIR_TEMPLATES":             "templates",
    "DIR_OUTPUT":                "output",
    "DIR_OUTPUT_QUADLETS":       "output/quadlets",
    "DIR_OUTPUT_CONFIGURATIONS": "output/configurations",
}

# ── Config loaders ────────────────────────────────────────────────────────────

def load_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file and return key-value pairs."""
    data: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            print(f"  {WARN}  Skipping malformed line {lineno}: {raw!r}")
            continue
        key, _, value = line.partition("=")
        # strip optional surrounding quotes
        value = value.strip().strip('"').strip("'")
        data[key.strip()] = value
    return data


def load_json_file(path: Path) -> dict[str, str]:
    """Load a JSON file and return a flat string dict."""
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("JSON root must be an object / dict")
    return {k: str(v) for k, v in raw.items()}


def load_yaml_file(path: Path) -> dict[str, str]:
    """
    Load template_build.yaml and extract directories from:
      1. system_directories  – flat key/value map of DIR_* entries
      2. paths               – templates_dir / output_dir
      3. templates_source    – all unique output_path values
    Returns a flat dict[str, str] of directory paths.
    """
    try:
        import yaml  # type: ignore
    except ImportError:
        print(f"  {FAIL}  PyYAML not installed. Run: pip install pyyaml")
        sys.exit(1)

    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("YAML root must be a mapping")

    result: dict[str, str] = {}

    # 1. system_directories section (DIR_* keys)
    sys_dirs = raw.get("system_directories", {})
    if isinstance(sys_dirs, dict):
        for k, v in sys_dirs.items():
            result[str(k)] = str(v)

    # 2. paths section (templates_dir / output_dir)
    paths_section = raw.get("paths", {})
    if isinstance(paths_section, dict):
        if "templates_dir" in paths_section:
            result["DIR_TEMPLATES"] = str(paths_section["templates_dir"])
        if "output_dir" in paths_section:
            result["DIR_OUTPUT"] = str(paths_section["output_dir"])

    # 3. templates_source – collect all unique output_path values
    for idx, entry in enumerate(raw.get("templates_source", [])):
        if isinstance(entry, dict) and "output_path" in entry:
            key = f"DIR_OUTPUT_SOURCE_{idx:02d}"
            result[key] = str(entry["output_path"])

    return result


def load_config(config_path: Path | None) -> tuple[dict[str, str], str]:
    """
    Try to load a config file in this order:
      1. Path supplied via --config
      2. ./template_build.yaml
      3. ./template_build.yml
      4. ./template_build.json
      5. ./template_build.env
      6. Fall back to built-in defaults
    Returns (variables_dict, source_description).
    """
    candidates: list[Path] = []
    if config_path:
        candidates = [config_path]
    else:
        candidates = [
            Path("template_build.yaml"),
            Path("template_build.yml"),
            Path("template_build.json"),
            Path("template_build.env"),
        ]

    for p in candidates:
        if not p.exists():
            continue
        suffix = p.suffix.lower()
        if suffix in (".yaml", ".yml"):
            return load_yaml_file(p), str(p)
        elif suffix == ".json":
            return load_json_file(p), str(p)
        elif suffix in (".env", ".conf", ""):
            return load_env_file(p), str(p)

    # nothing found – use defaults
    return DEFAULT_DIRECTORIES, "built-in defaults"


def extract_directories(variables: dict[str, str]) -> list[str]:
    """
    Pull directory paths from the variable dict.
    Accepts any key that starts with DIR_ or ends with _DIR,
    plus all default key names as a fallback set.
    """
    dir_keys = {k for k in variables if k.startswith("DIR_") or k.endswith("_DIR")}
    # also include any keys that match the default set
    dir_keys |= set(DEFAULT_DIRECTORIES.keys()) & set(variables.keys())

    paths = [variables[k] for k in sorted(dir_keys) if variables[k]]
    # deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique if unique else list(DEFAULT_DIRECTORIES.values())

# ── Permission / writability checks ──────────────────────────────────────────

def can_write_to(path: Path) -> tuple[bool, str]:
    """
    Check whether the current process can create files under `path`.
    Walks up the tree to find the highest existing ancestor.
    Returns (can_write, reason).
    """
    check = path
    while not check.exists():
        check = check.parent

    if os.access(check, os.W_OK):
        return True, f"writable (checked at {check})"

    # check if running as root
    if os.geteuid() == 0:
        return True, "running as root"

    return False, f"no write permission at {check} (try sudo)"


# ── Core logic ────────────────────────────────────────────────────────────────

def process_directories(directories: list[str], dry_run: bool) -> dict[str, bool]:
    results: dict[str, bool] = {}

    for raw_path in directories:
        path = Path(raw_path)
        can_write, reason = can_write_to(path)

        if dry_run:
            if path.exists():
                print(f"  {EXISTS}  {path}  →  already exists")
            else:
                perm_hint = f"{GREEN}✓ writable{RESET}" if can_write else f"{RED}✗ {reason}{RESET}"
                print(f"  {DRY}   {path}  →  would create  [{perm_hint}]")
            results[str(path)] = True
            continue

        # --- actual creation ---
        if path.exists():
            print(f"  {EXISTS}  {path}")
            results[str(path)] = True
            continue

        if not can_write:
            print(f"  {FAIL}  {path}  →  {reason}")
            results[str(path)] = False
            continue

        try:
            path.mkdir(parents=True, exist_ok=True)
            # verify we can actually write a file inside
            test_file = path / ".write_test"
            test_file.touch()
            test_file.unlink()
            print(f"  {OK}   {path}  →  created (writable)")
            results[str(path)] = True
        except PermissionError as e:
            print(f"  {FAIL}  {path}  →  permission denied: {e}")
            results[str(path)] = False
        except OSError as e:
            print(f"  {FAIL}  {path}  →  OS error: {e}")
            results[str(path)] = False

    return results


# ── Pretty header/footer ──────────────────────────────────────────────────────

def section(title: str) -> None:
    width = 62
    print(f"\n{BOLD}{CYAN}{'═' * width}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'═' * width}{RESET}")


def summary(results: dict[str, bool], dry_run: bool) -> None:
    section("SUMMARY")
    total  = len(results)
    passed = sum(1 for v in results.values() if v)

    for path, ok in results.items():
        status = OK if ok else FAIL
        print(f"  {status}  {path}")

    color = GREEN if passed == total else (YELLOW if passed >= total - 1 else RED)
    mode  = "dry-run preview" if dry_run else "directories created"
    print(f"\n  {color}{BOLD}Result: {passed}/{total} — {mode}{RESET}\n")

    if not dry_run and passed < total:
        print(f"  {YELLOW}Re-run with sudo for directories that failed due to permissions.{RESET}\n")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the directory structure for the Podman/NetBird stack."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview what would be created without making any changes."
    )
    parser.add_argument(
        "--config", metavar="FILE",
        help="Path to a template_build config file (.env / .json / .yaml). "
             "Defaults to auto-detecting template_build.* in the current directory."
    )
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else None

    # ── load config ───────────────────────────────────────────────────────────
    section("CONFIGURATION")
    try:
        variables, source = load_config(config_path)
    except Exception as e:
        print(f"  {FAIL}  Failed to load config: {e}")
        sys.exit(1)

    print(f"  {INFO}  Config source : {BOLD}{source}{RESET}")
    print(f"  {INFO}  Variables     : {len(variables)} entries loaded")

    directories = extract_directories(variables)
    print(f"  {INFO}  Directories   : {len(directories)} paths resolved")

    if args.dry_run:
        print(f"\n  {YELLOW}{BOLD}DRY-RUN MODE — no changes will be made{RESET}")

    # ── process ───────────────────────────────────────────────────────────────
    section("DRY-RUN PREVIEW" if args.dry_run else "CREATING DIRECTORIES")
    results = process_directories(directories, dry_run=args.dry_run)

    # ── summary ───────────────────────────────────────────────────────────────
    summary(results, dry_run=args.dry_run)

    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()