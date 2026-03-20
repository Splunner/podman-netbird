"""
Quadlet Volume & Network Generator
===================================
Reads configuration from a YAML file and renders Jinja2 templates
into the appropriate output directories.

Handles two types of Quadlet files:
  - volumes_quadlets : generated from inline config (no template file needed)
  - network_quadlets : rendered from user-provided Jinja2 template files

Usage:
    python generate_volume_and_network_quadlets.py [--config <path>] [--project-path <path>]

Defaults:
    --config        prod.yml  (resolved relative to --project-path)
    --project-path  current working directory
"""

import argparse
import os
import sys

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound


# ---------------------------------------------------------------------------
# Built-in Jinja2 template used for every volume quadlet.
# Variables injected:  name, location
# ---------------------------------------------------------------------------
VOLUME_TEMPLATE = """\
[Volume]
VolumeName={{ name }}
Device={{ location }}
Type=none
Options=bind
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> dict:
    """Load and parse the YAML configuration file.

    Args:
        config_path: Absolute or relative path to the YAML file.

    Returns:
        Parsed configuration as a Python dict.

    Raises:
        SystemExit: If the file is missing or contains invalid YAML.
    """
    if not os.path.isfile(config_path):
        sys.exit(f"[ERROR] Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as fh:
        try:
            config = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            sys.exit(f"[ERROR] Failed to parse YAML: {exc}")

    if not isinstance(config, dict):
        sys.exit("[ERROR] Config root must be a YAML mapping (dict).")

    return config


def ensure_dir(path: str) -> None:
    """Create directory (and all parents) if it does not already exist."""
    os.makedirs(path, exist_ok=True)


def write_file(dest_path: str, content: str) -> None:
    """Write *content* to *dest_path*, creating parent directories as needed."""
    ensure_dir(os.path.dirname(dest_path))
    with open(dest_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    print(f"  [OK] Written → {dest_path}")


# ---------------------------------------------------------------------------
# Volume generation
# ---------------------------------------------------------------------------

def generate_volumes(volumes: list[dict], project_path: str) -> None:
    """Generate one .volume quadlet file per entry in *volumes*.

    Each entry must contain:
        name     (str) – volume name, also used as the output filename
        location (str) – bind-mount path on the host

    Output filename convention:  <name>.volume
    Output directory:            <project_path>/output/quadlets/

    Args:
        volumes:      List of volume config dicts from the YAML file.
        project_path: Root directory of the project.
    """
    if not volumes:
        print("[SKIP] No volumes_quadlets defined in config.")
        return

    # Use Jinja2 even for the built-in template so rendering stays consistent
    env = Environment(undefined=StrictUndefined)
    tmpl = env.from_string(VOLUME_TEMPLATE)

    output_dir = os.path.join(project_path, "output", "quadlets")

    print(f"\n=== Generating volume quadlets → {output_dir} ===")

    for entry in volumes:
        # Validate required keys
        missing = [k for k in ("name", "location") if k not in entry]
        if missing:
            print(f"  [WARN] Skipping volume entry – missing keys: {missing}  entry={entry}")
            continue

        name: str = entry["name"].strip()
        location: str = entry["location"].strip().rstrip("/")  # normalise trailing slash

        rendered = tmpl.render(name=name, location=location)

        dest = os.path.join(output_dir, f"{name}.volume")
        write_file(dest, rendered)


# ---------------------------------------------------------------------------
# Network generation
# ---------------------------------------------------------------------------

def generate_networks(networks: list[dict], project_path: str, config: dict) -> None:
    """Render each network Jinja2 template and write the result to its output path.

    Each entry must contain:
        template_path (str) – path to the .j2 template, relative to project_path
        output_path   (str) – destination directory, relative to project_path

    The entire *config* dict is passed as template context so templates can
    reference any value defined in the YAML (e.g. {{ netbird_traefik.network_netbird }}).

    Args:
        networks:     List of network config dicts from the YAML file.
        project_path: Root directory of the project.
        config:       Full parsed YAML config (used as Jinja2 render context).
    """
    if not networks:
        print("[SKIP] No network_quadlets defined in config.")
        return

    print(f"\n=== Generating network quadlets ===")

    for entry in networks:
        # Validate required keys
        missing = [k for k in ("template_path", "output_path") if k not in entry]
        if missing:
            print(f"  [WARN] Skipping network entry – missing keys: {missing}  entry={entry}")
            continue

        template_rel: str = entry["template_path"]  # e.g. templates/netbird.network.j2
        output_rel: str   = entry["output_path"]     # e.g. output/quadlets

        template_abs = os.path.join(project_path, template_rel)
        output_dir   = os.path.join(project_path, output_rel)

        # Derive output filename by stripping the .j2 suffix
        template_filename = os.path.basename(template_rel)         # netbird.network.j2
        output_filename   = template_filename.removesuffix(".j2")   # netbird.network

        # Set up Jinja2 to load from the template's own directory so that
        # {% include %} / {% extends %} work if needed in the future
        template_dir = os.path.dirname(template_abs)

        env = Environment(
            loader=FileSystemLoader(template_dir),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )

        try:
            tmpl = env.get_template(template_filename)
        except TemplateNotFound:
            print(f"  [WARN] Template not found, skipping: {template_abs}")
            continue

        # Pass the entire config as context – templates can reference any key
        rendered = tmpl.render(**config)

        dest = os.path.join(output_dir, output_filename)
        write_file(dest, rendered)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Podman Quadlet volume and network unit files from a YAML config."
    )
    parser.add_argument(
        "--config",
        default="prod.yml",
        help="Path to the YAML configuration file (default: prod.yml).",
    )
    parser.add_argument(
        "--project-path",
        default=os.getcwd(),
        help="Project root directory. All relative paths are resolved from here (default: CWD).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    project_path = os.path.abspath(args.project_path)
    config_path  = os.path.join(project_path, args.config) \
                   if not os.path.isabs(args.config) \
                   else args.config

    print(f"Project path : {project_path}")
    print(f"Config file  : {config_path}")

    config = load_config(config_path)

    # Generate volume quadlets (built-in template, no .j2 file needed)
    volumes = config.get("volumes_quadlets", [])
    generate_volumes(volumes, project_path)

    # Generate network quadlets (user-supplied .j2 templates)
    networks = config.get("network_quadlets", [])
    generate_networks(networks, project_path, config)

    print("\n[DONE] All quadlets generated successfully.")


if __name__ == "__main__":
    main()