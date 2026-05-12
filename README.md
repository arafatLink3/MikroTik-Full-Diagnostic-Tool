# 🔧 MikroTik Full Diagnostic Tool

A comprehensive automated diagnostic & monitoring tool for MikroTik routers in ISP environments.

---

## 📦 Installation

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Edit your config
nano config.yaml
```

---

## ▶️ Usage

### Run for a single router (quick mode)
```bash
python mikrotik_diagnostic.py --host 192.168.1.1 --user admin --password yourpass
```

### Run for a specific router from config
```bash
python mikrotik_diagnostic.py --router "Core-Router-01"
```

### Run for all routers in config
```bash
python mikrotik_diagnostic.py --all
```

### Run as a scheduled service (every 15 min)
```bash
python scheduler.py
```

---

## 📊 What It Checks

| Module              | Details                                              |
|---------------------|------------------------------------------------------|
| System Info         | CPU, RAM, uptime, RouterOS version, board model      |
| Interfaces          | Status, speed, TX/RX errors, dropped packets         |
| IP & Routing        | IP addresses, active routes, ARP table, DNS          |
| BGP                 | Peer states, established sessions, prefix counts     |
| OSPF                | Neighbor states, interface participation             |
| PPPoE Sessions      | Active count vs total accounts                       |
| Queues              | Simple & tree queues, drop counts (congestion)       |
| Firewall            | Filter/NAT rule hits, active connections             |
| IP Pools            | Pool utilization per pool                            |
| Hotspot             | Active users, host counts                            |
| Wireless            | Connected clients per SSID                           |
| System Health       | Voltage, temperature (if hardware supports)          |
| Logs                | Last 30 critical/error/warning log entries           |

---

## 📲 Telegram Alerts

1. Message `@BotFather` on Telegram → `/newbot` → get your `BOT_TOKEN`
2. Add the bot to your NOC group
3. Get the group `chat_id` using `@userinfobot`
4. Fill in `config.yaml`

**Scheduler sends alerts ONLY when issues are detected:**
- CPU above threshold
- BGP/OSPF peer down
- Critical/error log entries
- Interface errors
- Connection failures

---

## 📁 Reports

All reports are saved automatically to the `reports/` folder:
```
reports/
  Core-Router-01_20250421_143022.txt
  Edge-Router-02_20250421_143045.txt
```

---

## ⚙️ Run as systemd Service (Linux)

```ini
# /etc/systemd/system/mikrotik-diag.service
[Unit]
Description=MikroTik Diagnostic Scheduler
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/mikrotik-diagnostic/scheduler.py
WorkingDirectory=/opt/mikrotik-diagnostic
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable mikrotik-diag
sudo systemctl start mikrotik-diag
```

---

## 📁 File Structure

```
mikrotik_diagnostic/
├── mikrotik_diagnostic.py   ← Main diagnostic engine
├── scheduler.py             ← Auto-run on schedule
├── config.yaml              ← Router list + Telegram config
├── requirements.txt         ← Python packages
├── README.md
└── reports/                 ← Auto-generated report files
```
