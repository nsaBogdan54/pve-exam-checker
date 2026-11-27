# -*- coding: utf-8 -*-
"""Вырезает из дампа Модуля 2 фрагмент вывода, соответствующий строке проверки."""
import re
import html


def find_evidence(msg, machines):
    parts = []
    br = machines.get("BR-SRV", {})
    hq = machines.get("HQ-SRV", {})
    cli = machines.get("HQ-CLI", {})
    isp = machines.get("ISP", {})

    # Пункт 1: Samba DC и sudo
    if any(k in msg for k in ("Samba DC", "длины пароля", "длина пароля", "блокировки", "пользователей", "группу")):
        s = br.get("samba_dc", "")
        if s:
            parts.append("===== BR-SRV: Samba DC =====\n" + s)

    if any(k in msg for k in ("введена в домен", "распознаются системой", "права sudo")):
        d = cli.get("domain_client", "")
        if d:
            parts.append("===== HQ-CLI: Домен и sudo =====\n" + d.replace("|", "\n"))

    # Пункт 2: RAID 0
    if any(k in msg for k in ("массив", "/raid", "fstab")):
        for title, key in (("cat /proc/mdstat", "raid"), ("mdadm --detail", "mdadm_detail"), ("mount", "mount"), ("/etc/fstab", "fstab")):
            val = hq.get(key, "")
            if val:
                parts.append(f"===== HQ-SRV: {title} =====\n{val}")

    # Пункт 3: NFS
    if any(k in msg for k in ("nfs-server", "/raid/nfs", "экспортирован", "экспорта")):
        ns = hq.get("nfs_server", "")
        if ns:
            parts.append("===== HQ-SRV: NFS Server =====\n" + ns)

    if "/mnt/nfs" in msg:
        nc = cli.get("nfs_client", "")
        if nc:
            parts.append("===== HQ-CLI: NFS Client =====\n" + nc)

    # Пункт 4: Chrony / NTP
    if any(k in msg for k in ("chronyd", "NTP-сервер", "stratum", "синхронизация времени", "NTP-клиент")):
        if "ISP:" in msg:
            cs = isp.get("chrony_server", "")
            if cs:
                parts.append("===== ISP: /etc/chrony.conf =====\n" + cs)
        for dev in ("HQ-SRV", "HQ-CLI", "BR-SRV"):
            if f"{dev}:" in msg:
                src = machines.get(dev, {}).get("sources", "")
                tr = machines.get(dev, {}).get("chrony_client", "")
                parts.append(f"===== {dev}: chronyc =====\n{src}\n\n{tr}".strip())
        if "BR-RTR:" in msg:
            raw = machines.get("BR-RTR", {}).get("raw", "")
            ntp_lines = [l for l in raw.splitlines() if l.startswith("ntp ")]
            if ntp_lines:
                parts.append("===== BR-RTR: running-config =====\n" + "\n".join(ntp_lines))

    # Пункт 5: Ansible
    if "Ansible" in msg:
        inv = br.get("ansible", "")
        png = br.get("ansible_ping", "")
        if inv:
            parts.append("===== BR-SRV: ansible-inventory =====\n" + inv)
        if png:
            parts.append("===== BR-SRV: ansible all -m ping =====\n" + png)

    # Пункт 6: Docker
    if "Docker" in msg:
        dk = br.get("docker", "")
        if dk:
            parts.append("===== BR-SRV: Docker =====\n" + dk)

    # Пункт 7: Web HQ
    if "Web HQ" in msg:
        wh = hq.get("web_hq", "")
        if wh:
            parts.append("===== HQ-SRV: Web (Apache + MariaDB) =====\n" + wh)

    # Пункт 8: DNAT
    if "DNAT" in msg:
        dt = isp.get("dnat_test", "")
        if dt:
            parts.append("===== ISP: Проверка портов DNAT =====\n" + dt)
        for rtr in ("HQ-RTR", "BR-RTR"):
            if rtr in msg:
                raw = machines.get(rtr, {}).get("raw", "")
                nat_lines = [l for l in raw.splitlines() if "ip nat" in l]
                if nat_lines:
                    parts.append(f"===== {rtr}: ip nat =====\n" + "\n".join(nat_lines))

    # Пункт 9: Яндекс.Браузер
    if "Браузер" in msg:
        brw = cli.get("browser", "")
        if brw:
            parts.append("===== HQ-CLI: Пакеты браузера =====\n" + brw)

    if not parts:
        return ""
    return html.escape("\n\n".join(parts))
