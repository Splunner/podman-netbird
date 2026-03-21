#!/usr/bin/env python3
"""
quadlets_generations.py

Generates Podman container quadlet files (.container) from Jinja2 templates
using variables defined in prod.yml and the build list from template_builds.yml
(section: templates_source, filtered to output_path containing "quadlets").

Conditional generation based on prod.yml flags:
    use_keycloak_IDP        → keycloak-manager.container.j2, postgres-db.container.j2
    use_postgres_on_netbird → postgres-db-netbird.container.j2
All other quadlets are always generated.

Usage:
    python3 quadlets_generations.py \
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
from jinja2 import Environment, FileSystemLoader


# ---------------------------------------------------------------------------
# Conditional container templates — template filename fragment → prod.yml flag
# ---------------------------------------------------------------------------

CONDITIONAL_CONTAINERS: dict[str, str] = {
    "keycloak-manager.container": "use_keycloak_IDP",
    "postgres-db.container":      "use_keycloak_IDP",
    "postgres-db-netbird.container": "use_postgres_on_netbird",
}


def container_is_enabled(template_path: str, prod: dict) -> tuple[bool, str]:
    """
    Return (enabled, reason) based on prod.yml feature flags.
    More specific names are checked first to avoid substring collisions.
    Templates not listed in CONDITIONAL_CONTAINERS are always enabled.
    """
    name = Path(template_path).name
    # Check most specific first
    for fragment in sorted(CONDITIONAL_CONTAINERS, key=len, reverse=True):
        if fragment in name:
            flag    = CONDITIONAL_CONTAINERS[fragment]
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


def extract_quadlet_entries(templates_config: "dict | list") -> list:
    """
    Extract quadlet entries from template_builds.yml.
    Reads 'templates_source' key and filters to output_path containing 'quadlets'.
    Falls back to a bare list filtered the same way.
    """
    if isinstance(templates_config, dict):
        source = templates_config.get("templates_source", [])
        if isinstance(source, list):
            return [e for e in source if "quadlets" in e.get("output_path", "")]
        raise ValueError(
            "template_builds.yml: key 'templates_source' not found or not a list."
        )
    if isinstance(templates_config, list):
        return [e for e in templates_config if "quadlets" in e.get("output_path", "")]
    raise ValueError("template_builds.yml: unexpected format.")


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def build_context(prod: dict) -> dict:
    """All top-level prod.yml keys are passed through to Jinja2 as-is."""
    return dict(prod)


# ---------------------------------------------------------------------------
# Existing-file checker
# ---------------------------------------------------------------------------

def check_existing_files(
    entries: list,
    src_project: Path,
    prod: dict,
) -> list[Path]:
    existing = []
    for entry in entries:
        template_rel = entry.get("template_path", "")
        enabled, _   = container_is_enabled(template_rel, prod)
        if not enabled:
            continue

        output_rel  = entry.get("output_path", "output/quadlets")
        output_name = entry.get("output_name", "")
        if not output_name:
            stem = Path(template_rel).name
            output_name = stem[:-3] if stem.endswith(".j2") else stem

        out_file = src_project / output_rel / output_name
        if out_file.exists():
            existing.append(out_file)
    return existing


# ---------------------------------------------------------------------------
# Template renderer
# ---------------------------------------------------------------------------

def render_template(
    template_path: str,
    output_path: str,
    output_name: str,
    ctx: dict,
) -> Path:
    tpl_file = Path(template_path)
    if not tpl_file.exists():
        raise FileNotFoundError(f"Template not found: {tpl_file}")

    env = Environment(
        loader=FileSystemLoader(str(tpl_file.parent)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    rendered = env.get_template(tpl_file.name).render(**ctx)

    if not output_name:
        stem = tpl_file.name
        output_name = stem[:-3] if stem.endswith(".j2") else stem

    out_dir  = Path(output_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / output_name
    out_file.write_text(rendered)
    return out_file


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_summary(
    generated:   list[Path],
    skipped:     list[tuple[str, str]],
    overwritten: list[Path],
) -> None:
    width = 60
    print()
    print("=" * width)
    print("  CONTAINER QUADLETS — GENERATION SUMMARY")
    print("=" * width)

    if generated:
        print(f"\n  ✔  Generated ({len(generated)} file(s)):")
        for f in generated:
            print(f"       {f}")

    if skipped:
        print(f"\n  ⊘  Skipped ({len(skipped)} template(s)):")
        for name, reason in skipped:
            print(f"       {name}")
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
        description="Generate Podman container quadlet files from Jinja2 templates.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Conditional generation (controlled by prod.yml flags):
  use_keycloak_IDP        → keycloak-manager.container, postgres-db.container
  use_postgres_on_netbird → postgres-db-netbird.container
        """,
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
            "Project root used to resolve relative template/output paths. "
            "Overrides $SRC_PROJECT_PODMAN_NETBIRD env var."
        ),
    )
    parser.add_argument(
        "--overdrive",
        action="store_true",
        default=False,
        help=(
            "Overwrite existing output files. "
            "Without this flag the script aborts if any target file already exists."
        ),
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

    print(f"prod.yml      : {prod_yml_path}")
    print(f"templates.yml : {templates_yml_path}")
    print(f"--overdrive   : {args.overdrive}\n")

    # --- Load YAML ------------------------------------------------------------
    prod_config      = load_yaml(str(prod_yml_path))
    templates_config = load_yaml(str(templates_yml_path))

    if not isinstance(prod_config, dict):
        print("[ERROR] prod.yml must be a YAML mapping.", file=sys.stderr)
        sys.exit(1)

    # --- Extract quadlet entries ----------------------------------------------
    try:
        entries = extract_quadlet_entries(templates_config)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    # --- Print feature flags --------------------------------------------------
    flag_keycloak    = bool(prod_config.get("use_keycloak_IDP", False))
    flag_netbird     = bool(prod_config.get("use_postgres_on_netbird", False))
    flag_letsencrypt = bool(prod_config.get("use_letsencrypt", False))
    print("Feature flags from prod.yml:")
    print(f"  use_keycloak_IDP        : {flag_keycloak}")
    print(f"  use_postgres_on_netbird : {flag_netbird}")
    print(f"  use_letsencrypt         : {flag_letsencrypt}")
    print(f"  Container entries found : {len(entries)}\n")

    # --- Guard: check for existing output files ------------------------------
    existing_files = check_existing_files(entries, src_project, prod_config)
    if existing_files and not args.overdrive:
        print("[ABORT] The following output files already exist:", file=sys.stderr)
        for f in existing_files:
            print(f"  ✘  {f}", file=sys.stderr)
        print("\nRe-run with --overdrive to overwrite them.", file=sys.stderr)
        sys.exit(1)

    # --- Build rendering context ---------------------------------------------
    ctx = build_context(prod_config)

    # --- Process templates ---------------------------------------------------
    print(f"Processing {len(entries)} container quadlet template(s)...\n")

    generated:  list[Path]            = []
    skipped:    list[tuple[str, str]] = []
    errors:     int                   = 0

    for idx, entry in enumerate(entries, start=1):
        template_rel = entry.get("template_path", "")
        output_rel   = entry.get("output_path", "output/quadlets")
        output_name  = entry.get("output_name", "")

        # --- Conditional skip ------------------------------------------------
        enabled, reason = container_is_enabled(template_rel, prod_config)
        if not enabled:
            print(f"  [{idx}/{len(entries)}] SKIP  {template_rel}")
            print(f"    reason : {reason}")
            skipped.append((template_rel, reason))
            continue

        template_abs = src_project / template_rel
        output_abs   = src_project / output_rel

        derived_name = output_name or (
            Path(template_rel).name[:-3]
            if template_rel.endswith(".j2")
            else Path(template_rel).name
        )

        print(f"  [{idx}/{len(entries)}] {template_rel}")
        print(f"    output : {output_abs / derived_name}")

        try:
            out_file = render_template(
                template_path = str(template_abs),
                output_path   = str(output_abs),
                output_name   = output_name,
                ctx           = ctx,
            )
            print(f"    [OK] Written → {out_file}")
            generated.append(out_file)
        except Exception as exc:
            print(f"    [ERROR] {exc}", file=sys.stderr)
            errors += 1

    # --- Summary -------------------------------------------------------------
    print_summary(
        generated   = generated,
        skipped     = skipped,
        overwritten = existing_files if args.overdrive else [],
    )

    if errors:
        print(f"[DONE] Completed with {errors} error(s).")
        sys.exit(1)
    else:
        print(f"[DONE] {len(generated)} container quadlet(s) generated, {len(skipped)} skipped.")


if __name__ == "__main__":
    main()