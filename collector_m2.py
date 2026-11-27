import os
import sys
import time
import re
import base64
import subprocess
import requests
import urllib3
import paramiko
from config import PROXMOX_HOST, PVE_USER, PVE_PASS
from variants_m2.loader import load_variant

urllib3.disable_warnings()
BASE_URL = f"https://{PROXMOX_HOST}:8006/api2/json"
MGMT_LOCAL_IP = "192.168.255.250/24"
MGMT_RTR_IP = "192.168.255.1"
IFACE = "ens18"


def b64_py(script_text):
    b64 = base64.b64encode(script_text.encode("utf-8")).decode("ascii")
    return f'python3 -c "import base64; exec(base64.b64decode(\'{b64}\'))" 2>&1'


def get_pve_session():
    res = requests.post(
        f"{BASE_URL}/access/ticket",
        data={"username": PVE_USER, "password": PVE_PASS},
        verify=False, timeout=5,
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
        cookies=cookies, headers=csrf,
        json={"command": ["sh", "-c", cmd]},
        verify=False, timeout=5,
    )
    if r_exec.status_code != 200:
        return f"[ОШИБКА АГЕНТА {r_exec.status_code}]: {r_exec.text.strip()}"
    pid = r_exec.json()["data"]["pid"]
    for _ in range(100):
        if progress_cb:
            progress_cb()
        time.sleep(0.3)
        st = requests.get(
            f"{BASE_URL}/nodes/{node}/qemu/{vmid}/agent/exec-status",
            cookies=cookies, params={"pid": pid},
            verify=False, timeout=5,
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


def build_m2_cmd(vm_name, var):
    n = vm_name.upper()
    parts = [
        "echo '--- HOSTNAME ---' && (hostnamectl --static 2>/dev/null || hostname)",
        "echo '--- IP -BR A ---' && ip -br a",
    ]

    if "ISP" in n:
        parts.append("echo '--- CHRONY SERVER ---' && echo 'SVC:' $(systemctl is-active chronyd 2>/dev/null) && grep -vE '^#|^$' /etc/chrony.conf 2>/dev/null || true")
        dnat_sh = (
            f"for t in HQ_WEB:172.16.1.2:{var.DNAT_WEB_PORT} HQ_SSH:172.16.1.2:{var.DNAT_SSH_PORT} "
            f"BR_WEB:172.16.2.2:{var.DNAT_WEB_PORT} BR_SSH:172.16.2.2:{var.DNAT_SSH_PORT}; do "
            "n=${t%%:*}; rest=${t#*:}; ip=${rest%%:*}; p=${rest#*:}; "
            "timeout 2 bash -c \"</dev/tcp/$ip/$p\" 2>/dev/null && echo \"$n: OK\" || echo \"$n: FAIL\"; done"
        )
        parts.append(f"echo '--- DNAT TEST ---' && ({dnat_sh})")

    if "HQ-SRV" in n or "HQ-CLI" in n or "BR-SRV" in n:
        parts.append("echo '--- CHRONY CLIENT ---' && (chronyc tracking 2>/dev/null; echo '--- SOURCES ---'; chronyc sources -n 2>/dev/null || true)")

    if "HQ-SRV" in n:
        parts.append(
            f"echo '--- RAID ---' && (cat /proc/mdstat 2>/dev/null; echo '--- MDADM DETAIL ---'; mdadm --detail /dev/{var.RAID_DEV} 2>/dev/null || true); "
            f"echo '--- FSTAB ---' && (grep '{var.RAID_MOUNT}' /etc/fstab 2>/dev/null || true); "
            f"echo '--- MOUNT ---' && (findmnt -n -o SOURCE,TARGET,FSTYPE '{var.RAID_MOUNT}' 2>/dev/null || echo 'NOT_MOUNTED'); "
            "echo '--- MDADM CONF ---' && (cat /etc/mdadm.conf 2>/dev/null || true)"
        )
        parts.append("echo '--- NFS SERVER ---' && echo 'SVC:' $(systemctl is-active nfs-server 2>/dev/null) && (exportfs -v 2>/dev/null || true)")
        web_py = (
            "import urllib.request\n"
            "try:\n"
            "    r = urllib.request.urlopen('http://127.0.0.1', timeout=2)\n"
            "    html = r.read().decode('utf-8', errors='ignore')\n"
            "    print(f'HTTP_CODE: {r.status} LEN: {len(html)}')\n"
            "    print(f'HAS_ERROR: {(\"error\" in html.lower() or \"failed\" in html.lower() or \"connect\" in html.lower() and \"denied\" in html.lower())}')\n"
            "except Exception as e:\n"
            "    print(f'HTTP_FAIL: {e}')\n"
        )
        parts.append(
            "echo '--- WEB HQ ---' && "
            "echo 'APACHE:' $(systemctl is-active httpd2 2>/dev/null || systemctl is-active apache2 2>/dev/null) && "
            "echo 'MARIADB:' $(systemctl is-active mariadb 2>/dev/null) && "
            f"echo 'DB_CHECK:' $(mysql -u{var.WEB_DB_USER} -p'{var.WEB_DB_PASS}' -e 'USE {var.WEB_DB_NAME}; SHOW TABLES;' 2>&1 | tr '\\n' ' ') && "
            "echo 'FILES:' $(find /var/www/ -maxdepth 3 \\( -name 'index.php' -o -name 'logo.png' \\) 2>/dev/null | tr '\\n' ' ') && "
            f"{b64_py(web_py)}"
        )

    if "HQ-CLI" in n:
        u1 = f"{var.USER_PREFIX}1"
        parts.append(
            "echo '--- DOMAIN CLIENT ---' && "
            "(realm list 2>/dev/null || wbinfo -t 2>/dev/null || true) && "
            f"echo 'ID_USER:' $(id {u1} 2>&1) && "
            f"echo 'SUDO_USER:' $(sudo -l -U {u1} 2>&1 | tr '\\n' '|')"
        )
        parts.append(f"echo '--- NFS CLIENT ---' && (findmnt -n -o SOURCE,TARGET,FSTYPE '{var.NFS_CLIENT_MOUNT}' 2>/dev/null || echo 'NOT_MOUNTED'); grep '{var.NFS_CLIENT_MOUNT}' /etc/fstab /etc/auto* 2>/dev/null || true")
        parts.append("echo '--- BROWSER ---' && (rpm -qa | grep -i yandex-browser || which yandex-browser yandex-browser-stable 2>/dev/null || echo 'NO_BROWSER')")

    if "BR-SRV" in n:
        parts.append(
            "echo '--- SAMBA DC ---' && "
            "echo 'SVC:' $(systemctl is-active samba 2>/dev/null) && "
            "(samba-tool domain passwordsettings show 2>/dev/null || true) && "
            "echo 'USERS:' $(samba-tool user list 2>/dev/null | tr '\\n' ' ') && "
            f"echo 'GRP_MEMBERS:' $(samba-tool group listmembers {var.DOMAIN_GROUP} 2>/dev/null | tr '\\n' ' ')"
        )
        parts.append(
            "echo '--- ANSIBLE ---' && "
            f"(cd {var.ANSIBLE_DIR} 2>/dev/null && ansible-inventory --list 2>&1 && echo '--- ANSIBLE PING ---' && ansible all -m ping 2>&1 || echo 'NO_ANSIBLE_DIR')"
        )
        docker_py = (
            "import urllib.request\n"
            "try:\n"
            f"    r = urllib.request.urlopen('http://127.0.0.1:{var.DOCKER_PORT}', timeout=2)\n"
            f"    print(f'HTTP_{var.DOCKER_PORT}: {{r.status}} LEN: {{len(r.read())}}')\n"
            "except Exception as e:\n"
            f"    print(f'HTTP_{var.DOCKER_PORT}_FAIL: {{e}}')\n"
        )
        parts.append(
            "echo '--- DOCKER ---' && "
            "echo 'SVC:' $(systemctl is-active docker 2>/dev/null) && "
            "echo 'PS:' $(docker ps --format '{{.Names}}|{{.Image}}|{{.Ports}}|{{.Status}}' 2>/dev/null | tr '\\n' ';') && "
            "echo 'COMPOSE:' $(find / -maxdepth 4 \\( -name 'compose.yaml' -o -name 'docker-compose.yml' \\) 2>/dev/null | tr '\\n' ' ') && "
            f"{b64_py(docker_py)}"
        )

    return " && ".join(parts)


def main():
    var_name = sys.argv[sys.argv.index("--variant") + 1] if "--variant" in sys.argv else None
    var = load_variant(var_name)
    skip_vals = {var_name} if var_name else set()
    args = [a for a in sys.argv[1:] if not a.startswith("-") and a not in skip_vals]
    verbose = True

    if not args:
        print("Использование: python3 collector_m2.py <ИМЯ_ПУЛА> [--variant default] [-v|--verbose]")
        sys.exit(1)

    pool_name = args.pop(0)
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
        sys.stdout.write(f"\r{ch} [{bar}] {idx}/{total} | Сбор Модуля 2 ({pool_name}): {vm_name:<12}")
        sys.stdout.flush()

    log("=" * 70)
    log(f"СБОР ДАННЫХ МОДУЛЯ 2 ПО ПУЛУ: {pool_name} (ВАРИАНТ: {var._VARIANT_NAME})")
    log("=" * 70)

    try:
        subprocess.run(["ip", "addr", "replace", MGMT_LOCAL_IP, "dev", IFACE], check=True)
        for idx, vm in enumerate(vms):
            name = vm.get("name", "")
            vmid = vm.get("vmid")
            node = vm.get("node")
            status = vm.get("status")
            cb = lambda: show_progress(idx, name)
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
                out = run_linux_cmd(node, vmid, build_m2_cmd(name, var), cookies, csrf, progress_cb=cb)
                log(out)
        if not verbose:
            sys.stdout.write(f"\r✔ [{'█' * 20}] {total}/{total} | Сбор Модуля 2 ({pool_name}) завершен!\n")
            sys.stdout.flush()
    finally:
        subprocess.run(["ip", "addr", "del", MGMT_LOCAL_IP, "dev", IFACE], stderr=subprocess.DEVNULL)

    pool_dir = os.path.join("dumps", pool_name)
    os.makedirs(pool_dir, exist_ok=True)
    out_file = os.path.join(pool_dir, f"latest_{pool_name}.txt")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    if verbose:
        print(f"\n[ГОТОВО] Дамп Модуля 2 сохранён в: {out_file}")


if __name__ == "__main__":
    main()
