#!/usr/bin/env python3
"""
MikroTik Full Diagnostic Tool
ISP Network Monitoring & Troubleshooting Automation
"""

import os
import sys
import json
import time
import yaml
import requests
import argparse
from datetime import datetime
from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.columns import Columns
from rich import box
from rich.text import Text
from rich.rule import Rule

console = Console()

# ─────────────────────────────────────────────
# Load Config
# ─────────────────────────────────────────────
def load_config(path="config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)


# ─────────────────────────────────────────────
# SSH Connection
# ─────────────────────────────────────────────
def connect(host, username, password, port=22):
    device = {
        "device_type": "mikrotik_routeros",
        "host": host,
        "username": username,
        "password": password,
        "port": port,
        "timeout": 15,
        "global_delay_factor": 2,
    }
    return ConnectHandler(**device)


# ─────────────────────────────────────────────
# Diagnostic Modules
# ─────────────────────────────────────────────

def get_system_info(conn):
    """CPU, RAM, uptime, version, identity"""
    data = {}
    data["identity"]    = conn.send_command("/system identity print")
    data["resources"]   = conn.send_command("/system resource print")
    data["routerboard"] = conn.send_command("/system routerboard print")
    data["clock"]       = conn.send_command("/system clock print")
    return data


def get_interface_status(conn):
    """All interfaces with status, speed, and errors"""
    data = {}
    data["summary"]  = conn.send_command("/interface print detail without-paging")
    data["ethernet"] = conn.send_command("/interface ethernet print stats")
    data["errors"]   = conn.send_command("/interface print stats where rx-error>0 or tx-error>0")
    return data


def get_ip_info(conn):
    """IP addresses, ARP table, routes"""
    data = {}
    data["addresses"] = conn.send_command("/ip address print")
    data["routes"]    = conn.send_command("/ip route print where active=yes")
    data["arp"]       = conn.send_command("/ip arp print")
    data["dns"]       = conn.send_command("/ip dns print")
    return data


def get_bgp_status(conn):
    """BGP peers, session states, prefixes"""
    data = {}
    data["peers"]     = conn.send_command("/routing bgp peer print detail")
    data["summary"]   = conn.send_command("/routing bgp peer print")
    data["advertised"]= conn.send_command("/routing bgp advertisements print count-only")
    return data


def get_ospf_status(conn):
    """OSPF neighbors and LSA database"""
    data = {}
    data["neighbors"] = conn.send_command("/routing ospf neighbor print")
    data["interfaces"]= conn.send_command("/routing ospf interface print")
    return data


def get_pppoe_status(conn):
    """Active PPPoE sessions count and details"""
    data = {}
    data["active_count"]  = conn.send_command("/ppp active print count-only")
    data["active_users"]  = conn.send_command("/ppp active print")
    data["secret_count"]  = conn.send_command("/ppp secret print count-only")
    return data


def get_queue_status(conn):
    """Simple and tree queues — drops indicate congestion"""
    data = {}
    data["simple"]     = conn.send_command("/queue simple print stats")
    data["tree"]       = conn.send_command("/queue tree print stats")
    data["dropped"]    = conn.send_command("/queue simple print where dropped>0")
    return data


def get_firewall_status(conn):
    """Firewall rules hit counts and connection tracking"""
    data = {}
    data["filter_rules"]  = conn.send_command("/ip firewall filter print stats")
    data["nat_rules"]     = conn.send_command("/ip firewall nat print stats")
    data["connections"]   = conn.send_command("/ip firewall connection print count-only")
    data["address_lists"] = conn.send_command("/ip firewall address-list print")
    return data


def get_ip_pool_usage(conn):
    """IP pool utilization"""
    data = {}
    data["pools"]  = conn.send_command("/ip pool print")
    data["used"]   = conn.send_command("/ip pool used print")
    return data


def get_hotspot_status(conn):
    """Hotspot active users and servers"""
    data = {}
    data["active"]  = conn.send_command("/ip hotspot active print count-only")
    data["hosts"]   = conn.send_command("/ip hotspot host print count-only")
    return data


def get_logs(conn, lines=30):
    """Recent error/warning logs"""
    data = {}
    data["errors"]   = conn.send_command(f"/log print where topics~\"error\" count={lines}")
    data["warnings"] = conn.send_command(f"/log print where topics~\"warning\" count={lines}")
    data["critical"] = conn.send_command(f"/log print where topics~\"critical\" count={lines}")
    return data


def get_health(conn):
    """Voltage, temperature (if supported)"""
    return conn.send_command("/system health print")


def get_wireless(conn):
    """Wireless interfaces and connected clients"""
    data = {}
    data["interfaces"]    = conn.send_command("/interface wireless print")
    data["registrations"] = conn.send_command("/interface wireless registration-table print")
    return data


# ─────────────────────────────────────────────
# Parse Resource Output for Key Metrics
# ─────────────────────────────────────────────
def parse_resources(resource_text):
    metrics = {}
    for line in resource_text.splitlines():
        line = line.strip()
        if "cpu-load:" in line:
            metrics["cpu"] = line.split(":")[1].strip().replace("%", "")
        elif "free-memory:" in line:
            metrics["free_mem"] = line.split(":")[1].strip()
        elif "total-memory:" in line:
            metrics["total_mem"] = line.split(":")[1].strip()
        elif "uptime:" in line:
            metrics["uptime"] = line.split(":")[1].strip()
        elif "version:" in line:
            metrics["version"] = line.split(":")[1].strip()
        elif "board-name:" in line:
            metrics["board"] = line.split(":")[1].strip()
        elif "cpu:" in line and "cpu-count" not in line and "cpu-load" not in line:
            metrics["cpu_model"] = line.split(":")[1].strip()
    return metrics


def parse_identity(identity_text):
    for line in identity_text.splitlines():
        if "name:" in line:
            return line.split(":")[1].strip()
    return "Unknown"


# ─────────────────────────────────────────────
# Rich Display Functions
# ─────────────────────────────────────────────

def display_header(router_name, host):
    console.print()
    console.print(Panel(
        f"[bold cyan]🔧 MikroTik Full Diagnostic Report[/bold cyan]\n"
        f"[white]Router:[/white] [yellow]{router_name}[/yellow]   "
        f"[white]Host:[/white] [yellow]{host}[/yellow]   "
        f"[white]Time:[/white] [yellow]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/yellow]",
        border_style="cyan",
        expand=True
    ))


def display_system_summary(resources_text, identity_text):
    metrics = parse_resources(resources_text)
    name = parse_identity(identity_text)

    cpu = int(metrics.get("cpu", 0))
    cpu_color = "green" if cpu < 60 else "yellow" if cpu < 85 else "red"

    table = Table(title="📊 System Overview", box=box.ROUNDED, border_style="cyan", expand=True)
    table.add_column("Metric", style="bold white")
    table.add_column("Value", style="cyan")
    table.add_column("Status", justify="center")

    table.add_row("Identity",    name,                          "✅")
    table.add_row("Board",       metrics.get("board", "N/A"),   "✅")
    table.add_row("RouterOS",    metrics.get("version", "N/A"), "✅")
    table.add_row("Uptime",      metrics.get("uptime", "N/A"),  "✅")
    table.add_row("CPU Load",    f"{cpu}%",                     f"[{cpu_color}]{'🟢' if cpu<60 else '🟡' if cpu<85 else '🔴'}[/{cpu_color}]")
    table.add_row("Free Memory", metrics.get("free_mem", "N/A"),  "ℹ️")
    table.add_row("Total Memory",metrics.get("total_mem", "N/A"), "ℹ️")

    console.print(table)


def display_section(title, content, max_lines=40):
    console.print(Rule(f"[bold cyan]{title}[/bold cyan]", style="cyan"))
    lines = content.strip().splitlines()
    if not lines or all(l.strip() == "" for l in lines):
        console.print("[dim]  No data returned.[/dim]")
    else:
        for line in lines[:max_lines]:
            # Colorize key states
            if "running" in line.lower():
                console.print(f"  [green]{line}[/green]")
            elif any(w in line.lower() for w in ["disabled", "inactive", "down", "error", "fail"]):
                console.print(f"  [red]{line}[/red]")
            elif any(w in line.lower() for w in ["established", "active", "up"]):
                console.print(f"  [cyan]{line}[/cyan]")
            elif "warning" in line.lower():
                console.print(f"  [yellow]{line}[/yellow]")
            else:
                console.print(f"  [white]{line}[/white]")
        if len(lines) > max_lines:
            console.print(f"  [dim]... {len(lines) - max_lines} more lines (see full report)[/dim]")


def display_pppoe_summary(pppoe_data):
    active = pppoe_data.get("active_count", "0").strip()
    secrets = pppoe_data.get("secret_count", "0").strip()
    console.print(Rule("[bold cyan]📡 PPPoE Sessions[/bold cyan]", style="cyan"))

    table = Table(box=box.SIMPLE, expand=False)
    table.add_column("Metric", style="bold white")
    table.add_column("Count", style="yellow", justify="right")
    table.add_row("Active Sessions", active)
    table.add_row("Total Accounts",  secrets)
    console.print(table)
    display_section("Active Sessions Detail", pppoe_data.get("active_users", ""), max_lines=20)


def display_logs_summary(logs_data):
    console.print(Rule("[bold red]📋 Recent Logs (Errors & Warnings)[/bold red]", style="red"))

    critical = logs_data.get("critical", "").strip()
    errors   = logs_data.get("errors", "").strip()
    warnings = logs_data.get("warnings", "").strip()

    if critical:
        console.print("[bold red]🚨 CRITICAL:[/bold red]")
        for line in critical.splitlines()[:10]:
            console.print(f"  [red]{line}[/red]")

    if errors:
        console.print("[bold yellow]⚠️  ERRORS:[/bold yellow]")
        for line in errors.splitlines()[:15]:
            console.print(f"  [yellow]{line}[/yellow]")

    if warnings:
        console.print("[bold white]ℹ️  WARNINGS:[/bold white]")
        for line in warnings.splitlines()[:10]:
            console.print(f"  [dim]{line}[/dim]")

    if not critical and not errors and not warnings:
        console.print("[green]  ✅ No critical errors or warnings found.[/green]")


# ─────────────────────────────────────────────
# Telegram Alert
# ─────────────────────────────────────────────
def send_telegram(bot_token, chat_id, message):
    if not bot_token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        console.print(f"[yellow]⚠ Telegram send failed: {e}[/yellow]")


def build_telegram_summary(router_name, host, resources_text, pppoe_data, logs_data):
    metrics = parse_resources(resources_text)
    cpu = metrics.get("cpu", "?")
    uptime = metrics.get("uptime", "?")
    active_pppoe = pppoe_data.get("active_count", "?").strip()
    has_errors = bool(logs_data.get("critical", "").strip() or logs_data.get("errors", "").strip())

    status_icon = "🔴" if int(cpu) > 85 else "🟡" if int(cpu) > 60 else "🟢"

    msg = (
        f"📡 *MikroTik Diagnostic Report*\n"
        f"Router: `{router_name}` ({host})\n"
        f"Time: `{datetime.now().strftime('%Y-%m-%d %H:%M')}`\n\n"
        f"{status_icon} *CPU Load:* {cpu}%\n"
        f"⏱ *Uptime:* {uptime}\n"
        f"👥 *Active PPPoE:* {active_pppoe}\n"
        f"{'🚨 *Errors found in logs!*' if has_errors else '✅ No critical errors'}\n"
    )
    return msg


# ─────────────────────────────────────────────
# Save Full Report to File
# ─────────────────────────────────────────────
def save_report(router_name, all_data):
    os.makedirs("reports", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"reports/{router_name.replace(' ', '_')}_{timestamp}.txt"

    with open(filename, "w") as f:
        f.write(f"MikroTik Diagnostic Report\n")
        f.write(f"Router: {router_name}\n")
        f.write(f"Generated: {datetime.now()}\n")
        f.write("=" * 80 + "\n\n")

        for section, data in all_data.items():
            f.write(f"\n{'='*40}\n{section.upper()}\n{'='*40}\n")
            if isinstance(data, dict):
                for key, value in data.items():
                    f.write(f"\n--- {key} ---\n{value}\n")
            else:
                f.write(str(data) + "\n")

    return filename


# ─────────────────────────────────────────────
# Main Diagnostic Runner
# ─────────────────────────────────────────────
def run_diagnostic(router_cfg, telegram_cfg=None):
    host     = router_cfg["host"]
    username = router_cfg["username"]
    password = router_cfg["password"]
    port     = router_cfg.get("port", 22)
    name     = router_cfg.get("name", host)

    display_header(name, host)

    steps = [
        ("System Info",        get_system_info),
        ("Interfaces",         get_interface_status),
        ("IP & Routing",       get_ip_info),
        ("BGP",                get_bgp_status),
        ("OSPF",               get_ospf_status),
        ("PPPoE Sessions",     get_pppoe_status),
        ("Queues",             get_queue_status),
        ("Firewall",           get_firewall_status),
        ("IP Pools",           get_ip_pool_usage),
        ("Hotspot",            get_hotspot_status),
        ("Wireless",           get_wireless),
        ("System Health",      lambda c: {"health": get_health(c)}),
        ("Logs",               get_logs),
    ]

    all_data = {}
    conn = None

    try:
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
            task = progress.add_task("[cyan]Connecting to router...", total=None)
            conn = connect(host, username, password, port)
            progress.update(task, description="[green]Connected! Running diagnostics...")

            for step_name, step_fn in steps:
                progress.update(task, description=f"[cyan]Collecting: {step_name}...")
                try:
                    all_data[step_name] = step_fn(conn)
                except Exception as e:
                    all_data[step_name] = {"error": str(e)}

    except NetmikoTimeoutException:
        console.print(f"[bold red]❌ Connection timeout to {host}[/bold red]")
        sys.exit(1)
    except NetmikoAuthenticationException:
        console.print(f"[bold red]❌ Authentication failed for {host}[/bold red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]❌ Connection error: {e}[/bold red]")
        sys.exit(1)
    finally:
        if conn:
            conn.disconnect()

    # ── Display Results ──
    sys_data = all_data.get("System Info", {})
    display_system_summary(
        sys_data.get("resources", ""),
        sys_data.get("identity", "")
    )

    display_section("🌐 Interfaces", all_data.get("Interfaces", {}).get("summary", ""))
    display_section("⚠️  Interface Errors", all_data.get("Interfaces", {}).get("errors", ""))
    display_section("🗺️  Active Routes", all_data.get("IP & Routing", {}).get("routes", ""))
    display_section("🔗 BGP Peers", all_data.get("BGP", {}).get("peers", ""))
    display_section("🔗 OSPF Neighbors", all_data.get("OSPF", {}).get("neighbors", ""))
    display_pppoe_summary(all_data.get("PPPoE Sessions", {}))
    display_section("📦 Queue Drops", all_data.get("Queues", {}).get("dropped", ""))
    display_section("🔥 Firewall Connections", all_data.get("Firewall", {}).get("connections", ""))
    display_section("🏊 IP Pool Usage", all_data.get("IP Pools", {}).get("used", ""))
    display_section("🌡️  System Health", all_data.get("System Health", {}).get("health", ""))
    display_logs_summary(all_data.get("Logs", {}))

    # ── Save Report ──
    report_file = save_report(name, all_data)
    console.print()
    console.print(Panel(f"[green]✅ Full report saved:[/green] [cyan]{report_file}[/cyan]", border_style="green"))

    # ── Telegram Alert ──
    if telegram_cfg and telegram_cfg.get("enabled"):
        summary = build_telegram_summary(
            name, host,
            sys_data.get("resources", ""),
            all_data.get("PPPoE Sessions", {}),
            all_data.get("Logs", {})
        )
        send_telegram(telegram_cfg["bot_token"], telegram_cfg["chat_id"], summary)
        console.print("[cyan]📲 Telegram alert sent.[/cyan]")

    return all_data


# ─────────────────────────────────────────────
# CLI Entry Point
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="MikroTik Full Diagnostic Tool")
    parser.add_argument("--config",  default="config.yaml",     help="Config file path")
    parser.add_argument("--router",  default=None,              help="Run for a specific router name")
    parser.add_argument("--all",     action="store_true",       help="Run for all routers in config")
    parser.add_argument("--host",    default=None,              help="Quick: router IP (use with --user/--pass)")
    parser.add_argument("--user",    default="admin",           help="SSH username")
    parser.add_argument("--password",default="",               help="SSH password")
    args = parser.parse_args()

    # Quick single-host mode
    if args.host:
        router_cfg = {"host": args.host, "username": args.user, "password": args.password, "name": args.host}
        run_diagnostic(router_cfg)
        return

    # Config-based mode
    config = load_config(args.config)
    routers = config.get("routers", [])
    telegram = config.get("telegram", {})

    if not routers:
        console.print("[red]No routers defined in config.yaml[/red]")
        sys.exit(1)

    if args.router:
        routers = [r for r in routers if r["name"] == args.router]
        if not routers:
            console.print(f"[red]Router '{args.router}' not found in config.[/red]")
            sys.exit(1)

    for router in routers:
        run_diagnostic(router, telegram_cfg=telegram)
        if len(routers) > 1:
            console.print()
            console.print(Rule(style="dim"))
            time.sleep(2)


if __name__ == "__main__":
    main()