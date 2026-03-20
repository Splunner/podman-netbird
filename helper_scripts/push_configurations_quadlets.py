#!/usr/bin/env python3
"""
build_copy.py — copies configuration files and quadlets based on prod.yml.

Usage examples:
  # Explicit paths via prod.yml
  python3 build_copy.py --prod-yml prod.yml

  # Override source path from CLI
  python3 build_copy.py --prod-yml prod.yml --source-path /path/to/podman-netbird-test

  # Use defaults derived from $SRC_PROJECT_PODMAN_NETBIRD env-var (rootless mode)
  python3 build_copy.py --prod-yml prod.yml --default-rl
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def copy_file(src: Path, dest_dir: Path) -> None:
    """Copy *src* into *dest_dir*, creating intermediate directories as needed."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest_dir / src.name)
    print(f"  ✓  {src.name:<30} →  {dest_dir}/")


# ---------------------------------------------------------------------------
# Section: configurations
# ---------------------------------------------------------------------------

def copy_configurations(base_path: Path, config_files: dict) -> None:
    """
    Copy every file listed in *config_files* from
    ``<base_path>/output/configurations`` to the destination path given in
    the mapping value.

    config_files format (prod.yml):
        config_files:
          config.yaml:           /opt/configurations/netbird
          certs.yml:             /opt/configurations/traefik/dynamic
          .env-postgres:         /opt/configurations/postgres
    """
    source_dir = base_path / "output" / "configurations"

    if not source_dir.is_dir():
        print(f"ERROR: configurations directory does not exist: {source_dir}")
        sys.exit(1)

    print(f"\n[configurations]  source: {source_dir}")
    print("-" * 60)

    for filename, dest in config_files.items():
        src = source_dir / filename
        if not src.exists():
            print(f"  ⚠  SKIPPED : {filename:<30} — file not found")
            continue
        copy_file(src, Path(dest))


# ---------------------------------------------------------------------------
# Section: quadlets
# ---------------------------------------------------------------------------

def copy_quadlets(base_path: Path, rootless: bool, dest_override: Path | None = None) -> None:
    """
    Copy all quadlet files from ``<base_path>/output/quadlets`` to the
    appropriate systemd directory.

    Destination resolution order:
      1. *dest_override*  — explicit path passed by the caller (e.g. --default-rl)
      2. rootless=True    — ~/.config/containers/systemd
      3. rootless=False   — /etc/containers/systemd
    """
    source_dir = base_path / "output" / "quadlets"

    if not source_dir.is_dir():
        print(f"ERROR: quadlets directory does not exist: {source_dir}")
        sys.exit(1)

    if dest_override is not None:
        dest_dir = dest_override
    elif rootless:
        dest_dir = Path.home() / ".config" / "containers" / "systemd"
    else:
        dest_dir = Path("/etc/containers/systemd")

    mode_label = "rootless" if (rootless or dest_override) else "rootful"
    print(f"\n[quadlets]  source: {source_dir}")
    print(f"[quadlets]  mode  : {mode_label} → {dest_dir}")
    print("-" * 60)

    files = list(source_dir.iterdir())
    if not files:
        print("  ⚠  No files found in quadlets directory.")
        return

    for src in sorted(files):
        if src.is_file():
            copy_file(src, dest_dir)


# ---------------------------------------------------------------------------
# prod.yml loader
# ---------------------------------------------------------------------------

def load_prod_yml(prod_yml_path: Path) -> dict:
    """Parse *prod_yml_path* and return its contents as a dictionary."""
    if not prod_yml_path.exists():
        print(f"ERROR: prod.yml not found: {prod_yml_path}")
        sys.exit(1)

    with prod_yml_path.open() as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        print("ERROR: prod.yml has an invalid format (expected a YAML mapping).")
        sys.exit(1)

    return data


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copy configuration files and quadlets based on prod.yml."
    )
    parser.add_argument(
        "--prod-yml",
        required=True,
        metavar="PATH",
        help="Path to the prod.yml file.",
    )
    parser.add_argument(
        "--source-path",
        default=None,
        metavar="PATH",
        help=(
            "Path to the podman-netbird-test directory. "
            "Overrides 'source_path' from prod.yml."
        ),
    )
    parser.add_argument(
        "--default-rl",
        action="store_true",
        help=(
            "Use defaults for a rootless setup:\n"
            "  • source path  → $SRC_PROJECT_PODMAN_NETBIRD\n"
            "  • quadlets dst → ~/.config/containers/systemd\n"
            "  (overrides prod.yml values for both)"
        ),
    )
    args = parser.parse_args()

    config = load_prod_yml(Path(args.prod_yml))

    # ------------------------------------------------------------------
    # Resolve source_path
    # Priority: --default-rl > --source-path > prod.yml source_path
    # ------------------------------------------------------------------
    quadlets_dest_override: Path | None = None

    if args.default_rl:
        env_var = os.environ.get("SRC_PROJECT_PODMAN_NETBIRD")
        if not env_var:
            print(
                "ERROR: --default-rl requires the environment variable "
                "$SRC_PROJECT_PODMAN_NETBIRD to be set."
            )
            sys.exit(1)
        source_path = env_var
        quadlets_dest_override = Path.home() / ".config" / "containers" / "systemd"
        # Force rootless=True when using --default-rl
        rootless = True
    else:
        source_path = args.source_path or config.get("source_path")
        rootless = config.get("rootless_setup", False)

    config_files = config.get("config_files", {})

    # ------------------------------------------------------------------
    # Validate source_path
    # ------------------------------------------------------------------
    if not source_path:
        print(
            "ERROR: 'source_path' is not defined.\n"
            "  Add to prod.yml :  source_path: /path/to/podman-netbird-test\n"
            "  or pass via CLI :  --source-path /path/to/podman-netbird-test\n"
            "  or use defaults :  --default-rl  (reads $SRC_PROJECT_PODMAN_NETBIRD)"
        )
        sys.exit(1)

    if not config_files:
        print("ERROR: 'config_files' key is missing or empty in prod.yml.")
        sys.exit(1)

    base_path = Path(source_path).expanduser().resolve()
    if not base_path.is_dir():
        print(f"ERROR: Source directory does not exist: {base_path}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"source_path    : {base_path}")
    print(f"rootless_setup : {rootless}")
    print(f"config_files   : {len(config_files)} file(s) defined")
    if args.default_rl:
        print(f"--default-rl   : quadlets → {quadlets_dest_override}")

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    copy_configurations(base_path, config_files=config_files)
    copy_quadlets(base_path, rootless=rootless, dest_override=quadlets_dest_override)

    print("\n" + "=" * 60)
    print("Done.")


if __name__ == "__main__":
    main()