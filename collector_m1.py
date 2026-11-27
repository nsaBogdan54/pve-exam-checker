import os
import sys
import time
import re
import subprocess
import requests
import urllib3
import paramiko
from config import PROXMOX_HOST, PVE_USER, PVE_PASS
from variants_m1.loader import load_variant

urllib3.disable_warnings()
BASE_URL = f"https://{PROXMOX_HOST}:8006/api2/json"
MGMT_LOCAL_IP = "192.168.255.250/24"
MGMT_RTR_IP = "192.168.255.1"
IFACE = "ens18"


def get_pve_session():
    res = requests.post(
        f"{BASE_URL}/access/ticket",
        data={"username": PVE_USER, "password": PVE_PASS},
        verify=False,
        timeout=5,
    )
    res.raise_for_status()
    data = res.json()["data"]
    return {"PVEAuthCookie": data["ticket"]}, {"CSRFPreventionToken": data["CSRFPreventionToken"]}


def get_pool_vms(pool_name, cookies):
    res = requests.get(f"{BASE_URL}/cluster/resources?type=vm", cookies=cookies, verify=False, timeout=5).json()
    vms = [
        v for v in res.get("data", [])
        if v.get("type") == "qemu"
        and v.get("pool") == pool_name
        and "chkstset" not in v.get("name", "").lower()
        and "checkstud" not in v.get("name", "").lower()
    ]
    return sorted(vms, key=lambda x: x.get("vmid", 0))


def run_linux_cmd(node, vmid, cmd, cookies, csrf, progress_cb=None):
    r_exec = requests.post(
        f"{BASE_URL}/nodes/{node}/qemu/{vmid}/agent/exec",
        cookies=cookies,
        headers=csrf,
        json={"command": ["sh", "-c", cmd]},
        verify=False,
        timeout=5,
    )
    if r_exec.status_code != 200:
        return f"[ОШИБКА АГЕНТА {r_exec.status_code}]: {r_exec.text.strip()}"
    pid = r_exec.json()["data"]["pid"]
    for _ in range(50):
        if progress_cb:
            progress_cb()
        time.sleep(0.3)
        st = requests.get(
            f"{BASE_URL}/nodes/{node}/qemu/{vmid}/agent/exec-status",
            cookies=cookies,
            params={"pid": pid},
            verify=False,
            timeout=5,
        ).json().get("data", {})
        if st.get("exited") == 1:
            out = (st.get("out-data") or "").strip()
            err = (st.get("err-data") or "").strip()
            return out if out else err
    return "[ТАЙМАУТ АГЕНТА]"


def set_net0_link(node, vmid, link_up, cookies, csrf):
    cfg_url = f"{BASE_URL}/nodes/{node}/qemu/{vmid}/config"
    cfg = requests.get(cfg_url, cookies=cookies, verify=False, timeout=5).json().get("data", {})
    net0 = cfg.get("net0", "")
    if not net0:
        raise RuntimeError("Интерфейс net0 не найден в конфигурации ВМ")
    clean_net0 = re.sub(r",?link_down=\d+", "", net0)
    new_net0 = clean_net0 if link_up else f"{clean_net0},link_down=1"
    res = requests.post(cfg_url, cookies=cookies, headers=csrf, data={"net0": new_net0}, verify=False, timeout=5)
    res.raise_for_status()


def wait_for_ping(ip, max_wait=15, progress_cb=None):
    subprocess.run(["ip", "neigh", "del", ip, "dev", IFACE], stderr=subprocess.DEVNULL)
    start = time.time()
    while time.time() - start < max_wait:
        if progress_cb:
            progress_cb()
        res = subprocess.run(["ping", "-c", "1", "-W", "1", ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            return True
        time.sleep(0.3)
    return False


def fetch_ecorouter_config(node, vmid, cookies, csrf, progress_cb=None):
    try:
        set_net0_link(node, vmid, link_up=True, cookies=cookies, csrf=csrf)
        if not wait_for_ping(MGMT_RTR_IP, max_wait=15, progress_cb=progress_cb):
            return "[ОШИБКА]: Роутер не ответил на ping по 192.168.255.1"
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(MGMT_RTR_IP, username="admin", password="admin", timeout=5, look_for_keys=False, allow_agent=False)
            chan = client.invoke_shell()
            for cmd in ("", "enable\n", "terminal length 0\n"):
                if cmd:
                    chan.send(cmd)
                for _ in range(5):
                    if progress_cb:
                        progress_cb()
                    time.sleep(0.2)
                    if chan.recv_ready():
                        chan.recv(4096)
            chan.send("show running-config\n")
            for _ in range(8):
                if progress_cb:
                    progress_cb()
                time.sleep(0.2)
            chan.send("show users localdb\n")
            for _ in range(5):
                if progress_cb:
                    progress_cb()
                time.sleep(0.2)
            out = ""
            while chan.recv_ready():
                out += chan.recv(16384).decode("utf-8", errors="ignore")
                time.sleep(0.1)
            client.close()
            out = out.replace("\r", "")
            start_idx = out.find("!")
            return out[start_idx:] if start_idx != -1 else out
        except Exception as e:
            client.close()
            return f"[ОШИБКА SSH]: {e}"
    finally:
        try:
            set_net0_link(node, vmid, link_up=False, cookies=cookies, csrf=csrf)
        except Exception as e:
            print(f"\n[КРИТИЧНО] Не удалось вернуть link_down=1 на {vmid}: {e}")


def build_linux_cmd(vm_name, var):
    import base64
    n = vm_name.upper()
    parts = [
        "echo '--- HOSTNAME ---' && (hostnamectl --static 2>/dev/null || hostname)",
        "echo '--- RESOLV.CONF ---' && cat /etc/resolv.conf 2>/dev/null",
        "echo '--- IP -BR A ---' && ip -br a",
        "echo '--- IP ROUTE ---' && ip r",
        "echo '--- TIMEZONE ---' && (timedatectl show -p Timezone --value 2>/dev/null || date +%Z)",
    ]
    if "ISP" in n or "FW" in n:
        parts.append("echo '--- IP_FORWARD ---' && sysctl -n net.ipv4.ip_forward")
        parts.append("echo '--- NAT / FIREWALL ---' && (iptables-save -t nat 2>/dev/null; nft list ruleset 2>/dev/null)")
    if "SRV" in n:
        u = var.LINUX_USER
        parts.append(f"echo '--- USER SSHUSER ---' && (id {u} 2>/dev/null || echo 'NO_USER') && (sudo -l -U {u} 2>/dev/null || true)")
        parts.append("echo '--- SSHD CONFIG ---' && (sshd -T 2>/dev/null | grep -E '^(port|allowusers|maxauthtries|banner) ')")
        parts.append("echo '--- SSH BANNER ---' && (B=$(sshd -T 2>/dev/null | awk '/^banner /{print $2}'); [ -n \"$B\" ] && [ \"$B\" != \"none\" ] && cat \"$B\" 2>/dev/null)")
    if "HQ-SRV" in n:
        port53_script = (
            "import socket\n"
            "s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
            "s.settimeout(1.5)\n"
            "try:\n"
            "    s.sendto(b'\\x12\\x34\\x01\\x00\\x00\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x02ya\\x02ru\\x00\\x00\\x01\\x00\\x01', ('127.0.0.1', 53))\n"
            "    data, _ = s.recvfrom(512)\n"
            "    print(':53 UDP_OK' if data else 'NO_RESP')\n"
            "except Exception as e:\n"
            "    print('PORT_53_FAIL:', e)\n"
        )
        b64_53 = base64.b64encode(port53_script.encode()).decode()
        parts.append(f"echo '--- DNS SERVER ---' && python3 -c \"import base64; exec(base64.b64decode('{b64_53}'))\" 2>&1")
    if "HQ-SRV" in n or "BR-SRV" in n or "HQ-CLI" in n:
        dns_script = (
            "import socket\n"
            "socket.setdefaulttimeout(1.5)\n"
            "hs = ['hq-rtr.au-team.irpo', 'hq-srv.au-team.irpo', 'hq-cli.au-team.irpo', 'br-rtr.au-team.irpo', 'br-fw.au-team.irpo', 'br-srv.au-team.irpo']\n"
            "res_a, bad_a = {}, []\n"
            "for h in hs:\n"
            "    try:\n"
            "        res_a[h] = socket.gethostbyname(h)\n"
            "    except Exception as e:\n"
            "        bad_a.append(f'{h} ({e})')\n"
            "print('A:', res_a)\n"
            "if bad_a:\n"
            "    print('A_BAD:', '; '.join(bad_a))\n"
            "for tag, host in [('PTR_HQ', 'hq-srv.au-team.irpo'), ('PTR_BR', 'br-srv.au-team.irpo')]:\n"
            "    try:\n"
            "        ip = res_a.get(host) or socket.gethostbyname(host)\n"
            "        print(f'{tag}:', socket.gethostbyaddr(ip))\n"
            "    except Exception as e:\n"
            "        print(f'{tag}_FAIL:', e)\n"
            "try:\n"
            "    print('EXT:', socket.gethostbyname('ya.ru'))\n"
            "except Exception as e:\n"
            "    print('EXT_FAIL:', e)\n"
        )
        b64_dns = base64.b64encode(dns_script.encode()).decode()
        parts.append(f"echo '--- DNS TEST ---' && python3 -c \"import base64; exec(base64.b64decode('{b64_dns}'))\" 2>&1")
    return " && ".join(parts)


def main():
    var_name = sys.argv[sys.argv.index("--variant") + 1] if "--variant" in sys.argv else None
    var = load_variant(var_name)
    skip_vals = {var_name} if var_name else set()
    args = [a for a in sys.argv[1:] if not a.startswith("-") and a not in skip_vals]
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    if not args:
        print("Использование: python3 collector.py <ИМЯ_ПУЛА> [ТЕГ] [-v|--verbose]")
        sys.exit(1)
    pool_name = args.pop(0)
    tag = args.pop(0) if args else "latest"
    cookies, csrf = get_pve_session()
    vms = get_pool_vms(pool_name, cookies)
    if not vms:
        print(f"В пуле '{pool_name}' не найдено ни одной ВМ.")
        sys.exit(1)

    report_lines = []

    def log(text=""):
        if verbose:
            print(text)
        report_lines.append(text)

    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    spin_idx = 0
    total = len(vms)

    def show_progress(idx, vm_name):
        nonlocal spin_idx
        if verbose:
            return
        bar_len = 20
        filled = int(bar_len * idx / total)
        bar = "█" * filled + "░" * (bar_len - filled)
        ch = spinner[spin_idx % len(spinner)]
        spin_idx += 1
        sys.stdout.write(f"\r{ch} [{bar}] {idx}/{total} | Сбор данных ({pool_name}): {vm_name:<12}")
        sys.stdout.flush()

    log("=" * 70)
    log(f"СБОР ДАННЫХ ПО ПУЛУ: {pool_name} (ТЕГ: {tag})")
    log("=" * 70)

    try:
        subprocess.run(["ip", "addr", "replace", MGMT_LOCAL_IP, "dev", IFACE], check=True)
        for idx, vm in enumerate(vms):
            name = vm.get("name", "")
            vmid = vm.get("vmid")
            node = vm.get("node")
            status = vm.get("status")

            def cb():
                show_progress(idx, name)

            cb()
            log(f"\n{'#' * 70}")
            log(f"МАШИНА: {name} | VMID: {vmid} | НОДА: {node} | СТАТУС: {status}")
            log(f"{'#' * 70}")
            if status != "running":
                log("[ПРОПУСК] Машина выключена.")
                continue
            if "rtr" in name.lower():
                cfg = fetch_ecorouter_config(node, vmid, cookies, csrf, progress_cb=cb)
                log(cfg)
            else:
                out = run_linux_cmd(node, vmid, build_linux_cmd(name, var), cookies, csrf, progress_cb=cb)
                log(out)
        if not verbose:
            sys.stdout.write(f"\r✔ [{'█' * 20}] {total}/{total} | Сбор данных ({pool_name}) завершен!\n")
            sys.stdout.flush()
    finally:
        subprocess.run(["ip", "addr", "del", MGMT_LOCAL_IP, "dev", IFACE], stderr=subprocess.DEVNULL)

    pool_dir = os.path.join("dumps", pool_name)
    os.makedirs(pool_dir, exist_ok=True)
    out_file = os.path.join(pool_dir, f"{tag}_{pool_name}.txt")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    if verbose:
        print(f"\n[ГОТОВО] Полный дамп сохранен в файл: {out_file}")


if __name__ == "__main__":
    main()
