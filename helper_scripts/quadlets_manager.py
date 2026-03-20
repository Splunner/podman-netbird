#!/usr/bin/env python3
"""
quadlets_manager.py
Manages Podman quadlet files (networks, volumes, containers).

Usage:
  python3 quadlets_manager.py init <src_dir>
  python3 quadlets_manager.py init <src_dir> --dest ~/.config/containers/systemd
  python3 quadlets_manager.py --display <src_dir>
  python3 quadlets_manager.py --display <src_dir> --dest ~/.config/containers/systemd
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# ── ANSI colors ───────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

OK    = f"{GREEN}[  OK  ]{RESET}"
FAIL  = f"{RED}[ FAIL ]{RESET}"
WARN  = f"{YELLOW}[ WARN ]{RESET}"
INFO  = f"{CYAN}[ INFO ]{RESET}"
STEP  = f"{BOLD}[ STEP ]{RESET}"

# ── Load order ────────────────────────────────────────────────────────────────
# Within each type group, files are sorted by this prefix order
CONTAINER_ORDER = ["postgres", "keycloak", "netbird", "traefik"]

# ── Helpers ───────────────────────────────────────────────────────────────────

def section(title: str) -> None:
    width = 62
    print(f"\n{BOLD}{CYAN}{'═' * width}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'═' * width}{RESET}")


def run(cmd: str) -> tuple[int, str, str]:
    """Run a shell command, return (returncode, stdout, stderr)."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def run_live(cmd: str) -> int:
    """Run a shell command, streaming output directly to terminal."""
    result = subprocess.run(cmd, shell=True)
    return result.returncode


def daemon_reload() -> bool:
    section("DAEMON RELOAD")
    print(f"  {STEP}  systemctl --user daemon-reload")
    rc = run_live("systemctl --user daemon-reload")
    if rc == 0:
        print(f"  {OK}  daemon-reload completed")
        return True
    else:
        print(f"  {FAIL}  daemon-reload failed (exit code {rc})")
        return False


def service_name(filepath: Path) -> str:
    """
    Convert a quadlet filename to its systemd service name.
      netbird-server.container  ->  netbird-server.service
      netbird_data.volume       ->  netbird_data-volume.service
      netbird.network           ->  netbird-network.service
    """
    stem = filepath.stem
    ext  = filepath.suffix.lstrip(".")
    if ext == "container":
        return f"{stem}.service"
    else:
        return f"{stem}-{ext}.service"


# ── File discovery ────────────────────────────────────────────────────────────

def discover_files(src: Path) -> dict[str, list[Path]]:
    """Scan src directory and return files grouped by type."""
    groups: dict[str, list[Path]] = {"network": [], "volume": [], "container": []}
    for f in sorted(src.iterdir()):
        ext = f.suffix.lstrip(".")
        if ext in groups:
            groups[ext].append(f)
    return groups


def sort_by_prefix(files: list[Path]) -> list[Path]:
    """
    Sort files by CONTAINER_ORDER prefix.
    Files not matching any prefix are appended at the end.
    """
    buckets: dict[str, list[Path]] = {k: [] for k in CONTAINER_ORDER}
    rest: list[Path] = []

    for f in files:
        matched = False
        for prefix in CONTAINER_ORDER:
            if f.name.startswith(prefix):
                buckets[prefix].append(f)
                matched = True
                break
        if not matched:
            rest.append(f)

    ordered: list[Path] = []
    for prefix in CONTAINER_ORDER:
        ordered.extend(sorted(buckets[prefix]))
    ordered.extend(sorted(rest))
    return ordered


def build_ordered_list(groups: dict[str, list[Path]]) -> list[Path]:
    """Return full ordered list: networks → volumes → containers."""
    return (
        sort_by_prefix(groups["network"]) +
        sort_by_prefix(groups["volume"]) +
        sort_by_prefix(groups["container"])
    )


# ── INIT command ──────────────────────────────────────────────────────────────

def cmd_init(src: Path, dest: Path) -> None:
    section("INIT — copying quadlet files")
    print(f"  {INFO}  Source : {src}")
    print(f"  {INFO}  Dest   : {dest}")

    dest.mkdir(parents=True, exist_ok=True)

    groups = discover_files(src)
    all_files = build_ordered_list(groups)

    # copy all files grouped by type
    for type_name in ("network", "volume", "container"):
        files = sort_by_prefix(groups[type_name])
        if files:
            print(f"\n  {BOLD}── {type_name.upper()}S ──{RESET}")
        for f in files:
            target = dest / f.name
            shutil.copy2(f, target)
            print(f"  {OK}  {f.name}  →  {target}")

    print(f"\n  {INFO}  {len(all_files)} file(s) copied")

    # daemon-reload
    if not daemon_reload():
        sys.exit(1)

    # start in order: networks → volumes → containers
    section("STARTING SERVICES")
    for f in all_files:
        svc = service_name(f)
        print(f"\n  {STEP}  systemctl --user start {svc}")
        rc = run_live(f"systemctl --user start {svc}")
        if rc == 0:
            print(f"  {OK}  {svc} started")
        else:
            print(f"  {FAIL}  {svc} failed to start (exit code {rc})")

    section("DONE")


# ── DISPLAY command ───────────────────────────────────────────────────────────

def cmd_display(src: Path, dest: Path) -> None:
    section("DISPLAY — systemctl commands for all quadlet services")
    print(f"  {INFO}  Source : {src}")
    print(f"  {INFO}  Dest   : {dest}")

    groups = discover_files(src)
    all_files = build_ordered_list(groups)

    if not all_files:
        print(f"  {WARN}  No quadlet files found in {src}")
        sys.exit(1)

    services = [service_name(f) for f in all_files]

    # ── current status ────────────────────────────────────────────────────────
    section("CURRENT STATUS")
    for f, svc in zip(all_files, services):
        rc, out, _ = run(f"systemctl --user is-active {svc} 2>/dev/null")
        status = out.strip() if out else "unknown"
        color = GREEN if status == "active" else (RED if status in ("failed", "error") else YELLOW)
        ext = f.suffix.lstrip(".")
        tag = f"{YELLOW}[{ext:>9}]{RESET}"
        print(f"  {tag}  {color}●{RESET}  {svc:<45}  {color}{status}{RESET}")

    # ── START commands ────────────────────────────────────────────────────────
    section("START  (networks → volumes → containers)")
    print(f"  {CYAN}systemctl --user daemon-reload{RESET}\n")
    for f, svc in zip(all_files, services):
        ext = f.suffix.lstrip(".")
        tag = f"{YELLOW}[{ext:>9}]{RESET}"
        print(f"  {tag}  {GREEN}systemctl --user start   {svc}{RESET}")

    # ── STOP commands ─────────────────────────────────────────────────────────
    section("STOP   (containers → volumes → networks)")
    print(f"  {CYAN}systemctl --user daemon-reload{RESET}\n")
    for f, svc in zip(reversed(all_files), reversed(services)):
        ext = f.suffix.lstrip(".")
        tag = f"{YELLOW}[{ext:>9}]{RESET}"
        print(f"  {tag}  {RED}systemctl --user stop    {svc}{RESET}")

    # ── RESTART commands ──────────────────────────────────────────────────────
    section("RESTART  (stop reversed → start in order)")
    print(f"  {CYAN}systemctl --user daemon-reload{RESET}\n")
    print(f"  {BOLD}# --- stop ---{RESET}")
    for f, svc in zip(reversed(all_files), reversed(services)):
        ext = f.suffix.lstrip(".")
        tag = f"{YELLOW}[{ext:>9}]{RESET}"
        print(f"  {tag}  {RED}systemctl --user stop    {svc}{RESET}")
    print(f"\n  {BOLD}# --- start ---{RESET}")
    for f, svc in zip(all_files, services):
        ext = f.suffix.lstrip(".")
        tag = f"{YELLOW}[{ext:>9}]{RESET}"
        print(f"  {tag}  {GREEN}systemctl --user start   {svc}{RESET}")

    print()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    default_dest = Path.home() / ".config" / "containers" / "systemd"

    parser = argparse.ArgumentParser(
        description="Manage Podman quadlet files (networks, volumes, containers).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 quadlets_manager.py init ~/quadlets
  python3 quadlets_manager.py init ~/quadlets --dest /etc/containers/systemd
  python3 quadlets_manager.py --display ~/quadlets
  python3 quadlets_manager.py --display ~/quadlets --dest /etc/containers/systemd
        """
    )

    parser.add_argument(
        "command",
        nargs="?",
        choices=["init"],
        help="'init' — copy files, daemon-reload and start all services in order"
    )
    parser.add_argument(
        "src",
        type=Path,
        help="Directory containing quadlet files (.network, .volume, .container)"
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=default_dest,
        metavar="PATH",
        help=f"Destination directory for quadlet files (default: {default_dest})"
    )
    parser.add_argument(
        "--display",
        action="store_true",
        help="Print all systemctl commands (start / stop / restart) for every service"
    )

    args = parser.parse_args()

    src = args.src.expanduser().resolve()
    if not src.exists():
        print(f"  {FAIL}  Source directory does not exist: {src}")
        sys.exit(1)
    if not src.is_dir():
        print(f"  {FAIL}  Source path is not a directory: {src}")
        sys.exit(1)

    dest = args.dest.expanduser().resolve()

    if args.display:
        cmd_display(src, dest)
    elif args.command == "init":
        cmd_init(src, dest)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()