#!/usr/bin/env python3
"""
MikroTik Auto-Scheduler
Runs diagnostics on a schedule and sends Telegram alerts only when issues found.
Run this as a cron job or systemd service.

Cron example (every 15 minutes):
  */15 * * * * /usr/bin/python3 /opt/mikrotik-diagnostic/scheduler.py >> /var/log/mikrotik_diag.log 2>&1
"""

import time
import yaml
import schedule
from datetime import datetime
from mikrotik_diagnostic import run_diagnostic, load_config, send_telegram
from rich.console import Console

console = Console()

def check_all_routers(config):
    routers  = config.get("routers", [])
    telegram = config.get("telegram", {})
    thresholds = config.get("thresholds", {})

    for router in routers:
        console.print(f"\n[cyan]⏱ Running scheduled check: {router['name']}[/cyan]")
        try:
            data = run_diagnostic(router, telegram_cfg=None)  # Don't auto-send on every run

            # ── Smart alerting: only send if issues detected ──
            issues = detect_issues(data, thresholds)
            if issues and telegram.get("enabled"):
                msg = format_issues_alert(router["name"], router["host"], issues)
                send_telegram(telegram["bot_token"], telegram["chat_id"], msg)
                console.print("[yellow]⚠ Issues found — Telegram alert sent.[/yellow]")
            else:
                console.print("[green]✅ No issues found.[/green]")

        except Exception as e:
            # Alert on connection failure
            err_msg = f"🔴 *Connection Failed*\nRouter: `{router['name']}` ({router['host']})\nError: `{str(e)}`"
            if telegram.get("enabled"):
                send_telegram(telegram["bot_token"], telegram["chat_id"], err_msg)
            console.print(f"[red]❌ Failed: {e}[/red]")


def detect_issues(data, thresholds):
    issues = []

    # Check CPU
    from mikrotik_diagnostic import parse_resources
    resources_text = data.get("System Info", {}).get("resources", "")
    metrics = parse_resources(resources_text)
    cpu = int(metrics.get("cpu", 0))
    cpu_crit = thresholds.get("cpu_critical", 85)
    cpu_warn = thresholds.get("cpu_warning", 60)

    if cpu >= cpu_crit:
        issues.append(f"🔴 CPU Critical: {cpu}% (threshold: {cpu_crit}%)")
    elif cpu >= cpu_warn:
        issues.append(f"🟡 CPU High: {cpu}% (threshold: {cpu_warn}%)")

    # Check errors in logs
    logs = data.get("Logs", {})
    if logs.get("critical", "").strip():
        issues.append("🚨 Critical log entries found!")
    if logs.get("errors", "").strip():
        lines = len(logs["errors"].strip().splitlines())
        issues.append(f"⚠️ {lines} error log entries found")

    # Check interface errors
    iface_errors = data.get("Interfaces", {}).get("errors", "").strip()
    if iface_errors:
        issues.append(f"⚠️ Interface errors detected")

    # Check BGP peers
    bgp = data.get("BGP", {}).get("peers", "")
    if "idle" in bgp.lower() or "connect" in bgp.lower():
        issues.append("🔴 BGP peer down or connecting")

    # Check OSPF
    ospf = data.get("OSPF", {}).get("neighbors", "").strip()
    if "down" in ospf.lower():
        issues.append("🔴 OSPF neighbor down")

    return issues


def format_issues_alert(name, host, issues):
    issue_list = "\n".join(f"• {i}" for i in issues)
    return (
        f"⚠️ *Issues Detected on {name}*\n"
        f"Host: `{host}`\n"
        f"Time: `{datetime.now().strftime('%Y-%m-%d %H:%M')}`\n\n"
        f"{issue_list}"
    )


if __name__ == "__main__":
    config = load_config("config.yaml")
    interval = 15  # minutes

    console.print(f"[cyan]🕒 Scheduler started — checking every {interval} minutes[/cyan]")

    # Run immediately on start
    check_all_routers(config)

    # Then schedule
    schedule.every(interval).minutes.do(check_all_routers, config)

    while True:
        schedule.run_pending()
        time.sleep(60)