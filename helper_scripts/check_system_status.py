#!/usr/bin/env python3
"""
check_system_status.py
Checks system readiness for running Podman / NetBird.
"""

import os
import shutil
import subprocess
import socket
import sys
import ipaddress
import subprocess

# ── ANSI colors ───────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

OK   = f"{GREEN}[  OK  ]{RESET}"
FAIL = f"{RED}[ FAIL ]{RESET}"
WARN = f"{YELLOW}[ WARN ]{RESET}"
INFO = f"{CYAN}[ INFO ]{RESET}"

# ── helpers ───────────────────────────────────────────────────────────────────

def run(cmd: str) -> tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def header(title: str) -> None:
    width = 60
    print(f"\n{BOLD}{CYAN}{'═' * width}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'═' * width}{RESET}")


def row(status: str, label: str, detail: str = "") -> None:
    detail_str = f"  {YELLOW}→ {detail}{RESET}" if detail else ""
    print(f"  {status}  {label}{detail_str}")


# ── checks ────────────────────────────────────────────────────────────────────

results: dict[str, bool] = {}


# 1. PODMAN ───────────────────────────────────────────────────────────────────
def check_podman() -> None:
    header("1 / Podman")
    path = shutil.which("podman")
    if path:
        rc, out, _ = run("podman --version")
        ver = out if rc == 0 else "?"
        row(OK, "Podman is installed", f"{ver}  ({path})")
        results["podman"] = True
    else:
        row(FAIL, "Podman is NOT installed")
        results["podman"] = False


# 2. CGROUP v2 ─────────────────────────────────────────────────────────────────
def check_cgroup() -> None:
    header("2 / cgroup v2")

    # method 1 – mount
    rc, out, _ = run("mount | grep '^cgroup' | awk '{print $1}' | uniq")
    cgroup_types = set(out.splitlines()) if out else set()

    # method 2 – /sys/fs/cgroup/cgroup.controllers (only exists in v2)
    v2_file = os.path.exists("/sys/fs/cgroup/cgroup.controllers")

    # method 3 – stat fstype
    rc2, out2, _ = run("stat -fc %T /sys/fs/cgroup/")
    fstype = out2.strip()

    is_v2 = v2_file or fstype == "cgroup2fs" or "cgroup2" in cgroup_types

    if is_v2:
        row(OK, "cgroup v2 is active", f"fstype={fstype}")
        results["cgroup_v2"] = True
    elif "cgroup" in cgroup_types and not is_v2:
        row(FAIL, "cgroup v1 detected (v2 required)",
            "Enable cgroup v2: add 'systemd.unified_cgroup_hierarchy=1' to GRUB")
        results["cgroup_v2"] = False
    else:
        row(WARN, "Cannot determine cgroup version",
            f"fstype={fstype}, mount={cgroup_types or 'none'}")
        results["cgroup_v2"] = False


# 3. PORTS ────────────────────────────────────────────────────────────────────
PORTS_TO_CHECK = [
    (80,   "tcp", "HTTP"),
    (443,  "tcp", "HTTPS"),
    (3478, "udp", "STUN/TURN (NetBird)"),
]

def port_listening(port: int, proto: str) -> tuple[bool, str]:
    """
    Checks whether a port is being listened on locally (via ss)
    and whether the firewall allows traffic through (firewall-cmd or iptables).
    """
    # ss – check if any process is listening on the port
    if proto == "tcp":
        rc, out, _ = run(f"ss -tlnH sport = :{port} 2>/dev/null")
    else:
        rc, out, _ = run(f"ss -ulnH sport = :{port} 2>/dev/null")
    listening = bool(out.strip())

    # firewall-cmd
    rc_fw, out_fw, _ = run(
        f"firewall-cmd --query-port={port}/{proto} 2>/dev/null"
    )
    fw_open = (rc_fw == 0 and "yes" in out_fw)

    # iptables fallback (when firewalld is not available)
    rc_ipt, out_ipt, _ = run(
        f"iptables -C INPUT -p {proto} --dport {port} -j ACCEPT 2>/dev/null"
    )
    ipt_open = (rc_ipt == 0)

    detail_parts = []
    if listening:
        detail_parts.append("listening")
    if fw_open:
        detail_parts.append("firewalld: open")
    elif ipt_open:
        detail_parts.append("iptables: open")
    else:
        detail_parts.append("no firewall rule found or firewall inactive")

    return listening, ", ".join(detail_parts)


def check_ports() -> None:
    header("3 / Network ports")
    for port, proto, label in PORTS_TO_CHECK:
        listening, detail = port_listening(port, proto)
        key = f"port_{port}_{proto}"
        if listening:
            row(OK, f"Port {port}/{proto.upper()}  ({label})", detail)
            results[key] = True
        else:
            row(WARN, f"Port {port}/{proto.upper()}  ({label}) – not listening", detail)
            results[key] = False


# 4. net.ipv4.ip_unprivileged_port_start ──────────────────────────────────────
def check_unprivileged_port() -> None:
    header("4 / Unprivileged port binding (sysctl)")
    rc, out, _ = run("sysctl -n net.ipv4.ip_unprivileged_port_start 2>/dev/null")
    if rc == 0 and out.isdigit():
        val = int(out)
        if val <= 80:
            row(OK,
                f"net.ipv4.ip_unprivileged_port_start = {val}",
                "Non-root processes can bind port 80 and above")
            results["unprivileged_port"] = True
        else:
            row(FAIL,
                f"net.ipv4.ip_unprivileged_port_start = {val}",
                "Set to <= 80:  sysctl -w net.ipv4.ip_unprivileged_port_start=80")
            results["unprivileged_port"] = False
    else:
        row(WARN, "Cannot read sysctl net.ipv4.ip_unprivileged_port_start")
        results["unprivileged_port"] = False


# 5. ENVIRONMENT VARIABLE ──────────────────────────────────────────────────────
def check_env_var() -> None:
    header("5 / Environment variable")
    var = "SRC_PROJECT_PODMAN_NETBIRD"
    val = os.environ.get(var)
    if val:
        row(OK, f"${var}", f"= {val}")
        results["env_var"] = True
    else:
        row(FAIL, f"${var} is NOT set",
            f'Set it with:  export {var}="/path/to/project"')
        results["env_var"] = False


# 6. PUBLIC IP ─────────────────────────────────────────────────────────────────
def get_local_ips():
    """Pobiera adresy IP z interfejsów sieciowych"""
    ips = []

    try:
        result = subprocess.run(
            ["ip", "-4", "addr"],
            capture_output=True,
            text=True
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                ip = line.split()[1].split("/")[0]
                ips.append(ip)
    except Exception:
        pass

    return ips


def is_public_ip(ip: str) -> bool:
    """Sprawdza czy IP jest publiczne"""
    try:
        ip_obj = ipaddress.ip_address(ip)
        return not (
            ip_obj.is_private or
            ip_obj.is_loopback or
            ip_obj.is_link_local or
            ip_obj.is_reserved or
            ip_obj.is_multicast
        )
    except ValueError:
        return False


def check_public_ip() -> None:
    header("6 / Server public IP")

    local_ips = get_local_ips()
    public_ips = [ip for ip in local_ips if is_public_ip(ip)]

    if public_ips:
        row(INFO, f"Detected public IP(s): {BOLD}{', '.join(public_ips)}{RESET}")
        results["public_ip"] = True
    else:
        row(WARN, "No public IP found on network interfaces")
        results["public_ip"] = False

    print(f"\n  {YELLOW}⚠  IMPORTANT: The server MUST have a public IP address{RESET}")
    print(f"  {YELLOW}   for NetBird to work correctly (relay / STUN mode).{RESET}")

# ── SUMMARY ───────────────────────────────────────────────────────────────────

def summary() -> None:
    header("SUMMARY")
    total = len(results)
    passed = sum(1 for v in results.values() if v)

    checks_labels = {
        "podman":             "Podman installed",
        "cgroup_v2":          "cgroup v2",
        "port_80_tcp":        "Port 80/TCP",
        "port_443_tcp":       "Port 443/TCP",
        "port_3478_udp":      "Port 3478/UDP",
        "unprivileged_port":  "Unprivileged port binding (sysctl)",
        "env_var":            "Variable $SRC_PROJECT_PODMAN_NETBIRD",
        "public_ip":          "Public IP",
    }

    for key, label in checks_labels.items():
        status = OK if results.get(key) else FAIL
        row(status, label)

    color = GREEN if passed == total else (YELLOW if passed >= total - 2 else RED)
    print(f"\n  {color}{BOLD}Result: {passed}/{total} checks passed{RESET}\n")

    if passed < total:
        print(f"  {YELLOW}Fix the issues above before starting the Podman/NetBird environment.{RESET}\n")
    else:
        print(f"  {GREEN}System is ready to go! 🎉{RESET}\n")


# ── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{BOLD}  check_system_status.py  --  Podman / NetBird environment diagnostics{RESET}")
    check_podman()
    check_cgroup()
    check_ports()
    check_unprivileged_port()
    check_env_var()
    check_public_ip()
    summary()
    # exit code: 0 = all checks passed, 1 = one or more failures
    sys.exit(0 if all(results.values()) else 1)