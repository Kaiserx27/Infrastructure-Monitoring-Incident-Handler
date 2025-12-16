import os
import sys
import time
import json
import sqlite3
import socket
import platform
import subprocess
import logging
import argparse
from datetime import datetime

# =========================
# CONFIGURATION
# =========================

CONFIG_FILE = "hosts.json"
DB_FILE = "incidents.db"
LOG_FILE = "monitoring.log"

CHECK_INTERVAL = 10  # seconds
HTTP_TIMEOUT = 5
PING_COUNT = 1

# =========================
# LOGGING
# =========================

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# =========================
# DATABASE
# =========================

def init_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hostname TEXT,
            service TEXT,
            status TEXT,
            description TEXT,
            created_at TEXT,
            resolved_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def create_incident(hostname, service, description):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO incidents (hostname, service, status, description, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        hostname,
        service,
        "OPEN",
        description,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()

    logging.warning(f"INCIDENT CREATED: {hostname} | {service} | {description}")


def resolve_incident(hostname, service):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE incidents
        SET status = ?, resolved_at = ?
        WHERE hostname = ? AND service = ? AND status = 'OPEN'
    """, (
        "RESOLVED",
        datetime.now().isoformat(),
        hostname,
        service
    ))

    conn.commit()
    conn.close()

    logging.info(f"INCIDENT RESOLVED: {hostname} | {service}")

# =========================
# NETWORK CHECKS
# =========================

def ping_host(host):
    try:
        param = "-n" if platform.system().lower() == "windows" else "-c"
        command = ["ping", param, str(PING_COUNT), host]
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return result.returncode == 0
    except Exception as e:
        logging.error(f"Ping error: {e}")
        return False


def check_port(host, port):
    try:
        with socket.create_connection((host, port), timeout=HTTP_TIMEOUT):
            return True
    except Exception:
        return False


def check_http(host, port):
    try:
        conn = socket.create_connection((host, port), timeout=HTTP_TIMEOUT)
        request = f"GET / HTTP/1.1\r\nHost: {host}\r\n\r\n"
        conn.send(request.encode())
        response = conn.recv(1024).decode()
        conn.close()
        return "200" in response
    except Exception:
        return False

# =========================
# SERVICE MANAGEMENT
# =========================

def restart_service(service_name):
    try:
        subprocess.run(
            ["systemctl", "restart", service_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        logging.info(f"Service restarted: {service_name}")
        return True
    except Exception as e:
        logging.error(f"Service restart failed: {e}")
        return False

# =========================
# CONFIG LOADING
# =========================

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print("Config file not found!")
        sys.exit(1)

    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

# =========================
# MONITORING LOGIC
# =========================

def monitor_host(host_config, auto_restart=False):
    hostname = host_config["hostname"]
    ip = host_config["ip"]
    services = host_config.get("services", [])

    logging.info(f"Checking host: {hostname} ({ip})")

    if not ping_host(ip):
        create_incident(hostname, "NETWORK", "Host unreachable (ping failed)")
        return
    else:
        resolve_incident(hostname, "NETWORK")

    for service in services:
        name = service["name"]
        port = service["port"]
        type_ = service["type"]

        if not check_port(ip, port):
            create_incident(hostname, name, f"Port {port} not reachable")

            if auto_restart and "systemd" in service:
                restart_service(service["systemd"])
            continue

        if type_ == "http":
            if not check_http(ip, port):
                create_incident(hostname, name, "HTTP service error")
                continue

        resolve_incident(hostname, name)

# =========================
# CLI
# =========================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Infrastructure Monitoring & Incident Handler"
    )

    parser.add_argument(
        "--monitor",
        action="store_true",
        help="Start monitoring"
    )

    parser.add_argument(
        "--auto-restart",
        action="store_true",
        help="Automatically restart services on failure"
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Run single check and exit"
    )

    return parser.parse_args()

# =========================
# MAIN
# =========================

def main():
    args = parse_args()
    init_database()
    config = load_config()

    logging.info("Monitoring started")

    if args.once:
        for host in config["hosts"]:
            monitor_host(host, args.auto_restart)
        return

    if args.monitor:
        while True:
            for host in config["hosts"]:
                monitor_host(host, args.auto_restart)
            time.sleep(CHECK_INTERVAL)
    else:
        print("Use --monitor to start monitoring")


if __name__ == "__main__":
    main()
