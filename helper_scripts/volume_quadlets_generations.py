#!/usr/bin/env python3
"""
volume_quadlets_generations.py

Generates Podman volume quadlet files (.volume) from the volumes_quadlets
section of template_builds.yml and variables from prod.yml.

Each volume entry in template_builds.yml produces one .volume file.
Conditional volumes are skipped based on prod.yml feature flags:
    use_keycloak_IDP        → postgres_data
    use_postgres_on_netbird → postgres_data_netbird
All other volumes are always generated.

Usage:
    python3 volume_quadlets_generations.py \
        --prod-yml /path/to/prod.yml \
        --templates-yml /path/to/template_builds.yml \
        [--src-project /path/to/project] \
        [--overdrive]

Environment:
    SRC_PROJECT_PODMAN_NETBIRD  – project root fallback
"""

import argparse
import os
import sys
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Conditional volume mapping — volume name fragment → prod.yml flag
# ---------------------------------------------------------------------------

CONDITIONAL_VOLUMES: dict[str, str] = {
    "postgres_data_netbird": "use_postgres_on_netbird",
    "postgres_data":         "use_keycloak_IDP",        # must come after netbird variant
}


def volume_is_enabled(name: str, prod: dict) -> tuple[bool, str]:
    """
    Return (enabled, reason) based on prod.yml feature flags.
    Volumes not listed in CONDITIONAL_VOLUMES are always enabled.
    Order matters: more specific names (postgres_data_netbird) are checked first.
    """
    for fragment, flag in CONDITIONAL_VOLUMES.items():
        if fragment in name:
            enabled = bool(prod.get(flag, False))
            reason  = f"prod.yml flag '{flag}' = {prod.get(flag, False)}"
            return enabled, reason
    return True, "always enabled"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_yaml(path: str) -> "dict | list":
    with open(path, "r") as fh:
        return yaml.safe_load(fh)


def extract_volume_entries(templates_config: "dict | list") -> list:
    """Extract the volumes_quadlets list from template_builds.yml."""
    if isinstance(templates_config, dict):
        entries = templates_config.get("volumes_quadlets")
        if isinstance(entries, list):
            return entries
        raise ValueError(
            "template_builds.yml: key 'volumes_quadlets' not found or not a list."
        )
    if isinstance(templates_config, list):
        return templates_config
    raise ValueError("template_builds.yml: unexpected format.")


def render_volume(name: str, location: str) -> str:
    """Render a .volume quadlet file content from name and location."""
    # Normalise location: strip trailing slash
    device = location.rstrip("/")
    return (
        f"[Volume]\n"
        f"VolumeName={name}\n"
        f"Device={device}\n"
        f"Type=none\n"
        f"Options=bind\n"
    )


# ---------------------------------------------------------------------------
# Existing-file checker
# ---------------------------------------------------------------------------

def check_existing_files(
    entries: list,
    output_dir: Path,
    prod: dict,
) -> list[Path]:
    existing = []
    for entry in entries:
        name = entry.get("name", "")
        enabled, _ = volume_is_enabled(name, prod)
        if not enabled:
            continue
        out_file = output_dir / f"{name}.volume"
        if out_file.exists():
            existing.append(out_file)
    return existing


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_summary(
    generated:  list[Path],
    skipped:    list[tuple[str, str]],
    overwritten: list[Path],
) -> None:
    width = 60
    print()
    print("=" * width)
    print("  VOLUME QUADLETS — GENERATION SUMMARY")
    print("=" * width)

    if generated:
        print(f"\n  ✔  Generated ({len(generated)} file(s)):")
        for f in generated:
            print(f"       {f}")

    if skipped:
        print(f"\n  ⊘  Skipped ({len(skipped)} volume(s)):")
        for name, reason in skipped:
            print(f"       {name}.volume")
            print(f"         reason: {reason}")

    if overwritten:
        print(f"\n  ⚠  Overwritten ({len(overwritten)} file(s)) [--overdrive]:")
        for f in overwritten:
            print(f"       {f}")

    print()
    print("=" * width)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Podman volume quadlet files from template_builds.yml.",
    )
    parser.add_argument(
        "--prod-yml",
        default=None,
        metavar="PATH",
        help=(
            "Path to prod.yml. "
            "Default: $SRC_PROJECT_PODMAN_NETBIRD/configurations_build_settings/prod.yml"
        ),
    )
    parser.add_argument(
        "--templates-yml",
        default=None,
        metavar="PATH",
        help=(
            "Path to template_builds.yml. "
            "Default: $SRC_PROJECT_PODMAN_NETBIRD/configurations_build_settings/template_builds.yml"
        ),
    )
    parser.add_argument(
        "--src-project",
        default=None,
        metavar="PATH",
        help=(
            "Project root used to resolve output paths. "
            "Overrides $SRC_PROJECT_PODMAN_NETBIRD env var."
        ),
    )
    parser.add_argument(
        "--output-path",
        default="output/quadlets",
        metavar="PATH",
        help="Relative (to --src-project) or absolute output directory. Default: output/quadlets",
    )
    parser.add_argument(
        "--overdrive",
        action="store_true",
        default=False,
        help="Overwrite existing output files. Without this flag the script aborts if any target file already exists.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    # --- Resolve project root -------------------------------------------------
    src_project = Path(
        args.src_project
        or os.environ.get("SRC_PROJECT_PODMAN_NETBIRD")
        or str(Path(__file__).resolve().parent)
    )
    print(f"Project root  : {src_project}")

    # --- Resolve config file paths --------------------------------------------
    prod_yml_path = (
        Path(args.prod_yml)
        if args.prod_yml
        else src_project / "configurations_build_settings" / "prod.yml"
    )
    templates_yml_path = (
        Path(args.templates_yml)
        if args.templates_yml
        else src_project / "configurations_build_settings" / "template_builds.yml"
    )

    for p in (prod_yml_path, templates_yml_path):
        if not p.exists():
            print(f"[ERROR] Required file not found: {p}", file=sys.stderr)
            sys.exit(1)

    # --- Resolve output directory ---------------------------------------------
    output_dir = (
        Path(args.output_path)
        if Path(args.output_path).is_absolute()
        else src_project / args.output_path
    )

    print(f"prod.yml      : {prod_yml_path}")
    print(f"templates.yml : {templates_yml_path}")
    print(f"output dir    : {output_dir}")
    print(f"--overdrive   : {args.overdrive}\n")

    # --- Load YAML ------------------------------------------------------------
    prod_config      = load_yaml(str(prod_yml_path))
    templates_config = load_yaml(str(templates_yml_path))

    if not isinstance(prod_config, dict):
        print("[ERROR] prod.yml must be a YAML mapping.", file=sys.stderr)
        sys.exit(1)

    # --- Extract volumes_quadlets section ------------------------------------
    try:
        entries = extract_volume_entries(templates_config)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    # --- Print feature flags --------------------------------------------------
    flag_keycloak = bool(prod_config.get("use_keycloak_IDP", False))
    flag_netbird  = bool(prod_config.get("use_postgres_on_netbird", False))
    print("Feature flags from prod.yml:")
    print(f"  use_keycloak_IDP        : {flag_keycloak}")
    print(f"  use_postgres_on_netbird : {flag_netbird}")
    print(f"  Volume entries found    : {len(entries)}\n")

    # --- Guard: check for existing output files ------------------------------
    existing_files = check_existing_files(entries, output_dir, prod_config)
    if existing_files and not args.overdrive:
        print("[ABORT] The following output files already exist:", file=sys.stderr)
        for f in existing_files:
            print(f"  ✘  {f}", file=sys.stderr)
        print("\nRe-run with --overdrive to overwrite them.", file=sys.stderr)
        sys.exit(1)

    # --- Process volumes ------------------------------------------------------
    print(f"Processing {len(entries)} volume entry/entries...\n")

    output_dir.mkdir(parents=True, exist_ok=True)

    generated:  list[Path]            = []
    skipped:    list[tuple[str, str]] = []
    errors:     int                   = 0

    for idx, entry in enumerate(entries, start=1):
        name     = entry.get("name", "")
        location = entry.get("location", "")

        if not name:
            print(f"  [{idx}/{len(entries)}] [ERROR] missing 'name' field — skipping entry", file=sys.stderr)
            errors += 1
            continue

        # --- Conditional skip -------------------------------------------------
        enabled, reason = volume_is_enabled(name, prod_config)
        if not enabled:
            print(f"  [{idx}/{len(entries)}] SKIP  {name}.volume")
            print(f"    reason : {reason}")
            skipped.append((name, reason))
            continue

        out_file = output_dir / f"{name}.volume"
        print(f"  [{idx}/{len(entries)}] {name}.volume")
        print(f"    device : {location.rstrip('/')}")
        print(f"    output : {out_file}")

        try:
            content = render_volume(name, location)
            out_file.write_text(content)
            print(f"    [OK] Written → {out_file}")
            generated.append(out_file)
        except Exception as exc:
            print(f"    [ERROR] {exc}", file=sys.stderr)
            errors += 1

    # --- Summary --------------------------------------------------------------
    print_summary(
        generated   = generated,
        skipped     = skipped,
        overwritten = existing_files if args.overdrive else [],
    )

    if errors:
        print(f"[DONE] Completed with {errors} error(s).")
        sys.exit(1)
    else:
        print(f"[DONE] {len(generated)} volume quadlet(s) generated, {len(skipped)} skipped.")


if __name__ == "__main__":
    main()