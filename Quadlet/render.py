import os
import sys
import yaml
from jinja2 import Environment, FileSystemLoader

def expand_path(path):
    """Expand ~ and environment variables in paths."""
    return os.path.expandvars(os.path.expanduser(path))

def main(config_file):
    # Load YAML config
    with open(config_file, "r") as f:
        config = yaml.safe_load(f)

    # Inject home directory into template context
    config["home"] = os.path.expanduser("~")

    # Dynamic settings
    output_dir = expand_path(config["settings"]["output_dir"])
    template_dir = expand_path(config["settings"]["template_dir"])

    os.makedirs(output_dir, exist_ok=True)

    # Load Jinja2 templates
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)

    generated_services = []

    for container in config["containers"]:
        template_name = container["template"]
        output_name = container["output"]

        # Render template with context
        template = env.get_template(template_name)
        rendered = template.render(**config)

        # Write output
        output_path = os.path.join(output_dir, output_name)
        with open(output_path, "w") as f:
            f.write(rendered)

        print(f"Generated {output_path}")

        # Derive service name for enabling
        if output_name.endswith(".container"):
            service_name = output_name.replace(".container", ".service")
            generated_services.append(service_name)

    # Print systemctl commands
    print("\nNow run:")
    print("  systemctl --user daemon-reload")
    for service in generated_services:
        print(f"  systemctl --user enable {service}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python render.py <config.yaml>")
        sys.exit(1)
    main(sys.argv[1])