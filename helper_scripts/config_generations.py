#!/usr/bin/env python3
"""
config_generations.py

Generates configuration files from Jinja2 templates using variables
defined in prod.yml and the build list from template_builds.yml.

Usage:
    python3 config_generations.py \\
        --prod-yml /path/to/prod.yml \\
        --templates-yml /path/to/template_builds.yml \\
        [--src-project /path/to/project] \\
        [--overdrive]

Flags in prod.yml that control conditional generation:
    use_keycloak_IDP: true        → includes .env-keycloak-manager.j2 and .env-postgres.j2
    use_postgres_on_netbird: true → includes .env-postgres-netbird.j2

Environment:
    SRC_PROJECT_PODMAN_NETBIRD  – project root fallback
"""

import argparse
import os
import secrets
import string
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader


# ---------------------------------------------------------------------------
# config_generations.py processes ONLY configuration templates.
# Quadlet templates (output_path containing "quadlets") are intentionally skipped.
# ---------------------------------------------------------------------------

CONFIGURATIONS_PATH_MARKER = "configurations"


def is_configuration_entry(entry: dict) -> bool:
    """
    Return True only if this template_builds.yml entry targets the
    'configurations' output directory.  Quadlets and other targets are ignored.
    """
    output_path = entry.get("output_path", "")
    return CONFIGURATIONS_PATH_MARKER in output_path


# ---------------------------------------------------------------------------
# Templates that are conditionally skipped based on prod.yml feature flags
# ---------------------------------------------------------------------------

# Maps a fragment of the template filename → the prod.yml flag that enables it.
# If the flag is absent or False the template is skipped.
CONDITIONAL_TEMPLATES: dict[str, str] = {
    ".env-keycloak-manager": "use_keycloak_IDP",
    ".env-postgres.":        "use_keycloak_IDP",       # .env-postgres.j2 (not netbird)
    ".env-postgres-netbird": "use_postgres_on_netbird",
}


def template_is_enabled(template_path: str, prod: dict) -> tuple[bool, str]:
    """
    Return (enabled, reason) for *template_path* based on feature flags.
    Matches on a substring of the template filename.
    """
    name = Path(template_path).name
    for fragment, flag in CONDITIONAL_TEMPLATES.items():
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


def generate_password(length: int = 32) -> str:
    safe_chars = string.ascii_letters + string.digits + "!@#%^&*_-+="
    return "".join(secrets.choice(safe_chars) for _ in range(length))


def generate_key(byte_length: int = 32) -> str:
    return secrets.token_urlsafe(byte_length)


def resolve_generated_password(value: str, cache: dict, cache_key: str) -> str:
    if isinstance(value, str) and value.strip().lower() == "generate":
        if cache_key not in cache:
            cache[cache_key] = generate_password()
            print(f"    [GENERATED] password for '{cache_key}'")
        return cache[cache_key]
    return value


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def build_context(prod: dict, pw_cache: dict) -> dict:
    ctx = dict(prod)

    if "postgres_db" in ctx:
        raw = ctx["postgres_db"].get("postgres_db_password", "")
        ctx["postgres_db"]["postgres_db_password"] = resolve_generated_password(
            raw, pw_cache, "postgres_db_password"
        )

    if "postgres_db_netbird" in ctx:
        raw = ctx["postgres_db_netbird"].get("postgres_db_password", "")
        ctx["postgres_db_netbird"]["postgres_db_password"] = resolve_generated_password(
            raw, pw_cache, "postgres_db_netbird_password"
        )

    ctx["random_key"]   = generate_key(32)
    ctx["random_key_2"] = generate_key(32)
    print("    [GENERATED] random_key and random_key_2 for config.j2")

    return ctx


# ---------------------------------------------------------------------------
# Existing-file checker
# ---------------------------------------------------------------------------

def check_existing_files(
    entries: list[dict],
    src_project: Path,
    prod: dict,
) -> list[Path]:
    """
    Return a list of output files that already exist on disk,
    considering only templates that would actually be enabled.
    """
    existing = []
    for entry in entries:
        template_rel = entry.get("template_path", "")
        enabled, _   = template_is_enabled(template_rel, prod)
        if not enabled:
            continue

        output_rel  = entry.get("output_path", "output")
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
    variable_section: str,
    base_ctx: dict,
) -> Path:
    tpl_file = Path(template_path)
    if not tpl_file.exists():
        raise FileNotFoundError(f"Template not found: {tpl_file}")

    ctx = dict(base_ctx)

    if variable_section == "postgres_db":
        ctx["postgres_script_password_generator"] = (
            ctx.get("postgres_db", {}).get("postgres_db_password", "")
        )
    elif variable_section == "postgres_db_netbird":
        ctx["postgres_script_password_generator"] = (
            ctx.get("postgres_db_netbird", {}).get("postgres_db_password", "")
        )
    else:
        ctx["postgres_script_password_generator"] = ""

    env = Environment(
        loader=FileSystemLoader(str(tpl_file.parent)),
        keep_trailing_newline=True,
        trim_blocks=False,
        lstrip_blocks=False,
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
    generated: list[Path],
    skipped:   list[tuple[str, str]],
    existing:  list[Path],
    overdrive: bool,
) -> None:
    width = 60

    print()
    print("=" * width)
    print("  GENERATION SUMMARY")
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

    if existing and overdrive:
        print(f"\n  ⚠  Overwritten ({len(existing)} file(s)) [--overdrive]:")
        for f in existing:
            print(f"       {f}")
    elif existing and not overdrive:
        # Should not happen here (we abort earlier), but just in case
        print(f"\n  ✘  Already existing (not overwritten):")
        for f in existing:
            print(f"       {f}")

    print()
    print("=" * width)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate NetBird configuration files from Jinja2 templates.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Conditional generation (controlled by prod.yml flags):
  use_keycloak_IDP: true        → .env-keycloak-manager.j2, .env-postgres.j2
  use_postgres_on_netbird: true → .env-postgres-netbird.j2
        """,
    )
    parser.add_argument(
        "--prod-yml",
        required=False,
        default=None,
        metavar="PATH",
        help=(
            "Path to prod.yml. "
            "Default: $SRC_PROJECT_PODMAN_NETBIRD/configurations_build_settings/prod.yml"
        ),
    )
    parser.add_argument(
        "--templates-yml",
        required=False,
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

    # template_builds.yml: unwrap if nested under a key
    if isinstance(templates_config, dict):
        for key in ("configurations", "templates", "builds"):
            if key in templates_config and isinstance(templates_config[key], list):
                templates_config = templates_config[key]
                break
        else:
            for v in templates_config.values():
                if isinstance(v, list):
                    templates_config = v
                    break
    if not isinstance(templates_config, list):
        print("[ERROR] template_builds.yml must resolve to a YAML list.", file=sys.stderr)
        sys.exit(1)

    # --- Filter: keep only configuration entries, skip quadlets etc. ----------
    all_entries      = templates_config
    templates_config = [e for e in all_entries if is_configuration_entry(e)]
    ignored_count    = len(all_entries) - len(templates_config)
    if ignored_count:
        print(
            f"  [INFO] Ignored {ignored_count} non-configuration entry/entries "
            f"(quadlets or other targets) \u2014 not handled by this script.\n"
        )

    # --- Print active feature flags -------------------------------------------
    flag_keycloak = bool(prod_config.get("use_keycloak_IDP", False))
    flag_netbird  = bool(prod_config.get("use_postgres_on_netbird", False))
    print("Feature flags from prod.yml:")
    print(f"  use_keycloak_IDP        : {flag_keycloak}")
    print(f"  use_postgres_on_netbird : {flag_netbird}\n")

    # --- Guard: check for existing output files before doing anything ---------
    existing_files = check_existing_files(templates_config, src_project, prod_config)
    if existing_files and not args.overdrive:
        print("[ABORT] The following output files already exist:", file=sys.stderr)
        for f in existing_files:
            print(f"  ✘  {f}", file=sys.stderr)
        print(
            "\nRe-run with --overdrive to overwrite them.",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- Build rendering context ----------------------------------------------
    pw_cache = {}
    print("Building rendering context...")
    ctx = build_context(prod_config, pw_cache)

    # --- Process templates ----------------------------------------------------
    print(f"\nProcessing {len(templates_config)} template entry/entries...\n")

    generated: list[Path]              = []
    skipped:   list[tuple[str, str]]   = []
    errors:    int                     = 0

    for idx, entry in enumerate(templates_config, start=1):
        template_rel = entry.get("template_path", "")
        variable_sec = entry.get("variable", "")
        output_rel   = entry.get("output_path", "output")
        output_name  = entry.get("output_name", "")

        # --- Conditional skip check ------------------------------------------
        enabled, reason = template_is_enabled(template_rel, prod_config)
        if not enabled:
            print(f"  [{idx}/{len(templates_config)}] SKIP  {template_rel}")
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
        print(f"  [{idx}/{len(templates_config)}] {template_rel}")
        print(f"    variable : {variable_sec or '(none)'}")
        print(f"    output   : {output_abs / derived_name}")

        try:
            out_file = render_template(
                template_path    = str(template_abs),
                output_path      = str(output_abs),
                output_name      = output_name,
                variable_section = variable_sec,
                base_ctx         = ctx,
            )
            print(f"    [OK] Written → {out_file}")
            generated.append(out_file)
        except Exception as exc:
            print(f"    [ERROR] {exc}", file=sys.stderr)
            errors += 1

    # --- Summary --------------------------------------------------------------
    print_summary(
        generated = generated,
        skipped   = skipped,
        existing  = existing_files if args.overdrive else [],
        overdrive = args.overdrive,
    )

    if errors:
        print(f"[DONE] Completed with {errors} error(s).")
        sys.exit(1)
    else:
        print(f"[DONE] {len(generated)} file(s) generated, {len(skipped)} skipped.")


if __name__ == "__main__":
    main()