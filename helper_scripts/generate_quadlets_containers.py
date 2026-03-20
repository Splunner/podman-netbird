#!/usr/bin/env python3
"""
Template generator script.
Reads configuration from a YAML file and renders Jinja2 templates
into the appropriate output directories.

Usage:
    python generate.py [--config <path_to_yaml>] [--project-path <project_root>]

Defaults:
    --config       prod.yml  (in current directory or project root)
    --project-path current working directory
"""

import argparse
import secrets
import string
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pip install pyyaml")

try:
    from jinja2 import (
        Environment,
        FileSystemLoader,
        StrictUndefined,
        UndefinedError,
    )
except ImportError:
    sys.exit("Missing dependency: pip install jinja2")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEMPLATE_OUTPUT_MAP: Dict[str, str] = {
    ".env-keycloak-manager":       "configurations",
    ".env-postgres":               "configurations",
    "config":                      "configurations",
    "dashboard":                   "configurations",
    "keycloak-manager.container":  "quadlets",
    "netbird-dashboard.container": "quadlets",
    "netbird-server.container":    "quadlets",
    "netbird-treafik.container":   "quadlets",
    "postgres-db.container":       "quadlets",
}

# Static file written directly to output/configurations/ (no template needed)
CERTS_YML_CONTENT = """\
tls:
  stores:
    default:
      defaultCertificate:
        certFile: /certs/cert.pem
        keyFile: /certs/key.pem
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ensure_dir(path: Path) -> None:
    """Create directory (and parents) if it does not exist yet."""
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        print(f"  [mkdir] {path}")


def load_yaml(config_path: Path) -> dict:
    with config_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        sys.exit(f"ERROR: {config_path} did not parse to a YAML mapping.")
    return data


def generate_password(length: int = 32) -> str:
    """Generate a cryptographically random alphanumeric password."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_base64_key(bytes_count: int = 32) -> str:
    """Generate a cryptographically random base64 key.
    Equivalent to: openssl rand -base64 32
    """
    import base64
    return base64.b64encode(secrets.token_bytes(bytes_count)).decode("utf-8")


def resolve_rootless_socket(shell_cmd: str) -> str:
    """
    Run the shell command from prod.yml to discover the rootless podman socket path.
    Returns a ready-to-use bind-mount string, e.g.:
        /run/user/1000/podman/podman.sock:/var/run/docker.sock:ro
    """
    try:
        result = subprocess.run(
            shell_cmd,
            shell=True,
            capture_output=True,
            text=True,
            check=True,
        )
        socket_path = result.stdout.strip()
        if not socket_path:
            sys.exit(
                "ERROR: rootless_setup=true but the podman.socket Listen address resolved "
                "to an empty string.\n"
                "  Make sure 'systemctl --user enable --now podman.socket' is running."
            )
        return f"{socket_path}:/var/run/docker.sock:ro"
    except subprocess.CalledProcessError as exc:
        sys.exit(
            f"ERROR: failed to resolve rootless podman socket:\n"
            f"  command : {shell_cmd}\n"
            f"  stderr  : {exc.stderr.strip()}"
        )


# ---------------------------------------------------------------------------
# Context building
# ---------------------------------------------------------------------------

def build_context(cfg: dict) -> Dict[str, Any]:
    """
    Derive the full Jinja2 rendering context from the raw YAML dict.

    Extra variables injected by the script
    ───────────────────────────────────────
    random_key                          32-byte base64 key (generated once, reused across templates)
    random_key_2                        second 32-byte base64 key
    postgres_script_password_generator  password from postgres_db.postgres_db_password,
                                        OR randomly generated when value is "generate"
    keycloak_manager                    alias for YAML key 'keycloak-manager'
                                        (hyphens are invalid in Jinja2 identifiers)
    keycloak_network                    shortcut: netbird_traefik.network_keycloak
    network_netbird                     shortcut: netbird_traefik.network_netbird (full value)
    network_netbird_name                only the name part before the colon

    rootless_setup                      bool – passed straight to templates
    socket_treafik_rootful              bind-mount string for rootful mode
                                        (resolved from YAML or default)
    socket_treafik_rootless             bind-mount string for rootless mode
                                        (resolved by running the shell command from YAML)

    Templates decide which socket to use via:
        {% if rootless_setup %}
            Volume={{ socket_treafik_rootless }}
        {% else %}
            Volume={{ socket_treafik_rootful }}
        {% endif %}
    """
    ctx: Dict[str, Any] = dict(cfg)

    # --- random keys (single values reused for authSecret + encryptionKey) ---
    ctx["random_key"]   = generate_base64_key(32)
    ctx["random_key_2"] = generate_base64_key(32)

    # --- keycloak_manager: handle both hyphen and underscore variants ---
    keycloak_mgr = cfg.get("keycloak_manager") or cfg.get("keycloak-manager", {})
    ctx["keycloak_manager"] = keycloak_mgr

    # --- postgres password ---
    postgres_cfg = dict(cfg.get("postgres_db", {}))
    raw_pw = str(postgres_cfg.get("postgres_db_password", ""))
    if raw_pw.strip().lower() == "generate":
        generated_pw = generate_password(32)
        print(f"  [gen]  Postgres password generated → {generated_pw}")
        ctx["postgres_script_password_generator"] = generated_pw
        postgres_cfg["postgres_db_password"] = generated_pw
        ctx["postgres_db"] = postgres_cfg
    else:
        ctx["postgres_script_password_generator"] = raw_pw

    # --- traefik network shortcuts ---
    traefik_cfg = cfg.get("netbird_traefik", {})
    network_netbird_raw: str = str(traefik_cfg.get("network_netbird", ""))
    ctx["network_netbird"]      = network_netbird_raw
    ctx["network_netbird_name"] = network_netbird_raw.split(":")[0]
    ctx["keycloak_network"]     = traefik_cfg.get("network_keycloak", "")

    # --- rootless / rootful Traefik socket ---
    # Both values are always resolved and put into context.
    # The Jinja2 template picks the right one with {% if rootless_setup %}.
    rootless: bool = bool(cfg.get("rootless_setup", False))
    ctx["rootless_setup"] = rootless

    # rootful – static string, just read from YAML (or use sensible default)
    ctx["socket_treafik_rootful"] = (
        cfg.get("socket_treafik_rootful")
        or "/run/podman/podman.sock:/var/run/docker.sock:ro"
    )

    # rootless – run the shell command to get the real socket path
    rootless_cmd: str = (
        cfg.get("socket_treafik_rootless")
        or "systemctl --user show podman.socket --property=Listen "
           "| cut -d= -f2 | awk '{print $1}'"
    )

    if rootless:
        print(f"  [rootless] resolving podman socket …")
        ctx["socket_treafik_rootless"] = resolve_rootless_socket(rootless_cmd)
        print(f"  [rootless] socket → {ctx['socket_treafik_rootless']}")
    else:
        # Still populate the key so templates don't raise UndefinedError
        # when they reference it inside {% if rootless_setup %} blocks
        # (Jinja2 StrictUndefined checks ALL referenced vars, even in dead branches).
        ctx["socket_treafik_rootless"] = ""
        print(f"  [rootful]  socket → {ctx['socket_treafik_rootful']}")

    return ctx


# ---------------------------------------------------------------------------
# Directory bootstrap
# ---------------------------------------------------------------------------

def bootstrap_output_dirs(project_path: Path, cfg: dict) -> Tuple[Path, Path]:
    """Ensure output/quadlets and output/configurations exist."""
    output_base        = project_path / cfg.get("paths", {}).get("output_dir", "output")
    quadlets_dir       = output_base / "quadlets"
    configurations_dir = output_base / "configurations"

    print("\n[*] Ensuring output directories …")
    ensure_dir(quadlets_dir)
    ensure_dir(configurations_dir)

    return quadlets_dir, configurations_dir


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def stem_of(template_path: str) -> str:
    name = Path(template_path).name
    return name[:-3] if name.endswith(".j2") else name


def resolve_output_dir(
    template_path: str,
    explicit_output_path: Optional[str],
    quadlets_dir: Path,
    configurations_dir: Path,
) -> Path:
    if explicit_output_path:
        parts = Path(explicit_output_path).parts
        if parts and parts[0].lower() == "output":
            parts = parts[1:]
        return quadlets_dir.parent.joinpath(*parts) if parts else quadlets_dir.parent

    stem     = stem_of(template_path)
    dest_key = TEMPLATE_OUTPUT_MAP.get(stem, "configurations")
    return quadlets_dir if dest_key == "quadlets" else configurations_dir


def build_jinja_env(templates_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        # StrictUndefined: raises clearly on ANY missing variable or attribute.
        # This surfaces real errors instead of silently producing empty output.
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )


def _render_one(
    env: Environment,
    tpl_name: str,
    context: Dict[str, Any],
    out_file: Path,
    overwrite: bool = False,
) -> bool:
    if out_file.exists() and not overwrite:
        print(f"  [skip] {tpl_name:45s} (exists, use --overwrite to regenerate)")
        return False

    try:
        template = env.get_template(tpl_name)
    except Exception as exc:
        print(f"  [WARN] Could not load template '{tpl_name}': {exc}")
        return False

    try:
        rendered = template.render(**context)
    except UndefinedError as exc:
        print(f"  [WARN] Undefined variable in '{tpl_name}': {exc}")
        return False

    out_file.write_text(rendered, encoding="utf-8")
    print(f"  [ok]   {tpl_name:45s} → {out_file}")
    return True


def render_templates(
    project_path: Path,
    cfg: dict,
    context: Dict[str, Any],
    quadlets_dir: Path,
    configurations_dir: Path,
    overwrite: bool = False,
) -> None:
    templates_dir = project_path / cfg.get("paths", {}).get("templates_dir", "templates")
    if not templates_dir.is_dir():
        sys.exit(f"ERROR: templates directory not found: {templates_dir}")

    env = build_jinja_env(templates_dir)

    print("\n[*] Rendering templates …")

    rendered_outputs = set()

    # --- templates_source entries ---
    for entry in cfg.get("templates_source", []):
        tpl_path    = entry.get("template_path", "")
        output_path = entry.get("output_path", "")

        tpl_name    = Path(tpl_path).name
        out_dir     = resolve_output_dir(tpl_path, output_path, quadlets_dir, configurations_dir)
        ensure_dir(out_dir)

        # output_name in YAML overrides the default (strip .j2) filename
        default_name = tpl_name[:-3] if tpl_name.endswith(".j2") else tpl_name
        out_name     = entry.get("output_name", default_name)
        out_file     = out_dir / out_name
        if _render_one(env, tpl_name, context, out_file, overwrite=overwrite):
            rendered_outputs.add(out_file)

    # --- location_config_file / location_dashboard_file (legacy keys) ---
    for key, out_dir in (
        ("location_config_file",    configurations_dir),
        ("location_dashboard_file", configurations_dir),
    ):
        tpl_path_val = cfg.get(key)
        if not tpl_path_val:
            continue
        tpl_name = Path(tpl_path_val).name
        out_name = tpl_name[:-3] if tpl_name.endswith(".j2") else tpl_name
        out_file = out_dir / out_name
        if out_file not in rendered_outputs:
            _render_one(env, tpl_name, context, out_file, overwrite=overwrite)


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

def write_static_files(configurations_dir: Path, overwrite: bool = False) -> None:
    """Write static (non-templated) output files."""
    print("\n[*] Writing static files …")

    certs_file = configurations_dir / "certs.yml"
    if certs_file.exists() and not overwrite:
        print(f"  [skip] certs.yml (exists, use --overwrite to regenerate)")
        return
    certs_file.write_text(CERTS_YML_CONTENT, encoding="utf-8")
    print(f"  [ok]   certs.yml (static)                             → {certs_file}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--config", default=None,
                   help="Path to the YAML configuration file (default: prod.yml)")
    p.add_argument("--project-path", default=None,
                   help="Project root directory (default: directory containing the config file)")
    p.add_argument("--overwrite", action="store_true",
                   help="Overwrite existing output files (default: skip files that already exist)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # Resolve config file
    if args.config:
        config_path = Path(args.config).resolve()
    else:
        for candidate in (
            Path(__file__).parent / "prod.yml",
            Path.cwd() / "prod.yml",
        ):
            if candidate.exists():
                config_path = candidate
                break
        else:
            sys.exit("ERROR: Could not find prod.yml. Pass --config <path>.")

    if not config_path.exists():
        sys.exit(f"ERROR: Config file not found: {config_path}")

    project_path = (
        Path(args.project_path).resolve()
        if args.project_path
        else config_path.parent
    )

    print(f"[*] Config       : {config_path}")
    print(f"[*] Project root : {project_path}")

    cfg     = load_yaml(config_path)
    context = build_context(cfg)

    print("\n[*] Generated runtime values:")
    print(f"  random_key                        : {context['random_key']}")
    print(f"  random_key_2                      : {context['random_key_2']}")
    print(f"  postgres_script_password_generator: {context['postgres_script_password_generator']}")
    print(f"  keycloak_network                  : {context['keycloak_network']}")
    print(f"  network_netbird_name              : {context['network_netbird_name']}")
    print(f"  rootless_setup                    : {context['rootless_setup']}")
    print(f"  socket_treafik_rootful            : {context['socket_treafik_rootful']}")
    print(f"  socket_treafik_rootless           : {context['socket_treafik_rootless']}")

    # --- validate keycloak_manager ---
    km = context.get("keycloak_manager", {})
    if not km:
        print("\n  [WARN] keycloak_manager is EMPTY – check that 'keycloak-manager:' key exists in prod.yml")
    else:
        print(f"\n[*] keycloak_manager context:")
        for k, v in km.items():
            print(f"  {k}: {v}")

    quadlets_dir, configurations_dir = bootstrap_output_dirs(project_path, cfg)

    render_templates(project_path, cfg, context, quadlets_dir, configurations_dir,
                     overwrite=args.overwrite)

    write_static_files(configurations_dir, overwrite=args.overwrite)

    print("\n[✓] Done.")


if __name__ == "__main__":
    main()