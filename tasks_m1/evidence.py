# -*- coding: utf-8 -*-
"""Вырезает из дампа кусок конфига, соответствующий тексту проверки."""
import re
import html

MACHINE_KEYS = ("HQ-SRV", "HQ-CLI", "HQ-RTR", "BR-SRV", "BR-FW", "BR-RTR", "ISP")


def _machines_in_msg(msg):
    found = []
    for k in MACHINE_KEYS:
        if k in msg:
            found.append(k)
    return found


def _find_machine_by_ip(ip, machines):
    ip_only = ip.split("/")[0]
    for name, info in machines.items():
        for iface, ipif in info.get("ifaces", {}).items():
            if str(ipif.ip) == ip_only:
                return name, iface
    return None, None


def _block_until_bang(raw, start_pat):
    lines = raw.splitlines()
    for i, l in enumerate(lines):
        if re.search(start_pat, l):
            j = i
            while j < len(lines) and lines[j].strip() != "!":
                j += 1
            return "\n".join(lines[i:j])
    return ""


def _block_until(raw, start_pat, end_pat):
    lines = raw.splitlines()
    for i, l in enumerate(lines):
        if re.search(start_pat, l):
            j = i + 1
            while j < len(lines) and not re.search(end_pat, lines[j]):
                j += 1
            return "\n".join(lines[i:j])
    return ""


def _iface_lines_linux(info):
    out = []
    for iface, ipif in info.get("ifaces", {}).items():
        out.append(f"{iface:<8} UP {ipif}")
    return "\n".join(out)


def _highlight(text, msg):
    return html.escape(text)


def find_evidence(msg, machines):
    """По тексту строки отчёта возвращает HTML-доказательство (или '')."""
    parts = []
    devs = _machines_in_msg(msg)

    # ---------- Шлюзы / маршруты ----------
    if "Шлюз" in msg or "default via" in msg:
        for d in devs:
            info = machines.get(d, {})
            rt = info.get("routes_raw", "")
            if rt:
                parts.append(f"===== {d}: ip route =====\n{rt}")

    # ---------- FQDN ----------
    if "FQDN" in msg:
        for d in devs:
            info = machines.get(d, {})
            hn = info.get("hostname", "")
            raw = info.get("raw", "")
            src = f"hostnamectl --static -> {hn}"
            if raw:
                m = re.search(r"^hostname\s+(\S+)", raw, re.M)
                if m:
                    src = f"show running-config -> hostname {m.group(1)}"
            parts.append(f"===== {d}: hostname =====\n{src}")

    # ---------- Приватные IP ----------
    if "Приватный IP" in msg:
        m_ip = re.search(r"\((\S+?)\):\s*(\d+\.\d+\.\d+\.\d+/\d+)", msg)
        if m_ip and devs:
            iface, ipval = m_ip.group(1), m_ip.group(2)
            d = devs[0]
            info = machines.get(d, {})
            if "RTR" in d:
                blk = _block_until_bang(info.get("raw", ""), rf"^interface {re.escape(iface)}\b")
                parts.append(f"===== {d}: interface {iface} =====\n{blk}")
            else:
                ipif = info.get("ifaces", {}).get(iface)
                parts.append(f"===== {d}: ip -br a =====\n{iface:<8} UP {ipif}")

    # ---------- VLAN-стыки (две машины по IP) ----------
    if "VLAN" in msg and "<->" in msg:
        for ip in re.findall(r"\d+\.\d+\.\d+\.\d+/\d+", msg):
            d, iface = _find_machine_by_ip(ip, machines)
            if not d:
                continue
            info = machines.get(d, {})
            if "RTR" in d:
                blk = _block_until_bang(info.get("raw", ""), rf"^interface {re.escape(iface)}\b")
                parts.append(f"===== {d}: interface {iface} =====\n{blk}")
            else:
                ipif = info.get("ifaces", {}).get(iface)
                parts.append(f"===== {d}: ip -br a =====\n{iface:<8} UP {ipif}")

    # ---------- Пункт 4: VLAN 100, 200, 999 на одном порту HQ-RTR ----------
    if "Пункт 4" in msg or "на одном порту" in msg:
        for d in devs:
            raw = machines.get(d, {}).get("raw", "")
            if not raw or "RTR" not in d:
                continue
            # 1) найти порт с dot1q 999 и собрать его service-instance
            target_port = None
            port_body = ""
            port_si = []
            for m in re.finditer(r"^port\s+(\S+)\n((?: [^\n]*\n?)*)", raw, re.M):
                pname, pbody = m.group(1), m.group(2)
                vlans = re.findall(r"encapsulation dot1q (\d+)", pbody)
                if "999" in vlans:
                    target_port = pname
                    port_body = pbody
                    port_si = re.findall(r"service-instance (\S+)", pbody)
                    break
            if not target_port:
                continue
            parts.append("===== " + d + ": port " + target_port + " (dot1q) =====\n"
                         + ("port " + target_port + "\n" + port_body).rstrip())
            # 2) найти ВСЕ interface, привязанные к этому порту через service-instance
            for si in port_si:
                for im in re.finditer(r"^interface\s+(\S+)\n((?: [^\n]*\n?)*)", raw, re.M):
                    iname, ibody = im.group(1), im.group(2)
                    if ("connect port " + target_port + " service-instance " + si) in ibody:
                        parts.append("===== " + d + ": interface " + iname + " =====\n"
                                     + ("interface " + iname + "\n" + ibody).rstrip())
                        break

    # ---------- VLAN 999 (управленческая сеть) ----------
    if "VLAN 999" in msg or "vlan 999" in msg.lower():
        for d in devs:
            info = machines.get(d, {})
            raw = info.get("raw", "")
            if raw and "RTR" in d:
                for iname in info.get("ifaces", {}):
                    if "999" in iname.lower():
                        blk = _block_until_bang(raw, rf"^interface {re.escape(iname)}\b")
                        if blk:
                            parts.append("===== " + d + ": interface " + iname + " =====\n" + blk)
                        break
            elif info.get("ifaces"):
                for iname, ipif in info.get("ifaces", {}).items():
                    if ipif.network.prefixlen >= 29 and "999" in iname.lower():
                        parts.append("===== " + d + ": ip -br a =====\n" + _iface_lines_linux(info))
                        break

    # ---------- Внешний линк ISP ----------
    if "Внешний линк" in msg:
        for ip in re.findall(r"\d+\.\d+\.\d+\.\d+/\d+", msg):
            d, iface = _find_machine_by_ip(ip, machines)
            if not d:
                continue
            info = machines.get(d, {})
            if "RTR" in d:
                blk = _block_until_bang(info.get("raw", ""), rf"^interface {re.escape(iface)}\b")
                parts.append(f"===== {d}: interface {iface} =====\n{blk}")
            else:
                rt = info.get("routes_raw", "")
                if rt:
                    parts.append(f"===== {d}: ip route =====\n{rt}")

    # ---------- OSPF ----------
    if "OSPF" in msg and "OSPF):" in msg:
        for d in devs:
            raw = machines.get(d, {}).get("raw", "")
            if raw:
                blk = _block_until_bang(raw, r"^router ospf\b")
                if blk:
                    parts.append(f"===== {d}: router ospf =====\n{blk}")
        if "BR-FW" in msg:
            rt = machines.get("BR-FW", {}).get("routes_raw", "")
            if rt:
                parts.append(f"===== BR-FW: ip route =====\n{rt}")

    # ---------- MD5 ----------
    if "MD5" in msg:
        for d in devs:
            raw = machines.get(d, {}).get("raw", "")
            if raw:
                blk = _block_until_bang(raw, r"^interface tunnel\.0\b")
                if blk:
                    parts.append(f"===== {d}: interface tunnel.0 =====\n{blk}")

    # ---------- GRE ----------
    if "GRE" in msg:
        for d in devs:
            raw = machines.get(d, {}).get("raw", "")
            if raw:
                blk = _block_until_bang(raw, r"^interface tunnel\.0\b")
                if blk:
                    parts.append(f"===== {d}: interface tunnel.0 =====\n{blk}")

    # ---------- NAT ----------
    if "NAT" in msg or "nat" in msg and "ip nat" in msg:
        for d in devs:
            info = machines.get(d, {})
            raw = info.get("raw", "")
            if raw:
                lines = [l for l in raw.splitlines() if "ip nat" in l]
                if lines:
                    parts.append(f"===== {d}: ip nat (show running-config) =====\n" + "\n".join(lines))
                blk = _block_until(raw, r"^ip nat source", r"^!")
                if blk:
                    parts.append(f"===== {d}: правило NAT =====\n{blk}")
            nat = info.get("nat", "")
            if nat:
                parts.append(f"===== {d}: iptables-save -t nat =====\n{nat}")
            fwd = info.get("ip_forward", "")
            if fwd and "форвардинг" in msg:
                parts.append(f"===== {d}: net.ipv4.ip_forward =====\n{fwd}")

    # ---------- SSH ----------
    if "SSH" in msg or "баннер" in msg or "AllowUsers" in msg or "MaxAuthTries" in msg or "порту" in msg:
        for d in devs:
            info = machines.get(d, {})
            sshd = info.get("sshd", "")
            ban = info.get("banner", "")
            if sshd:
                parts.append(f"===== {d}: sshd -T =====\n{sshd}")
            if ban:
                parts.append(f"===== {d}: файл баннера =====\n{ban}")

    # ---------- SSH (порт, AllowUsers, MaxAuthTries, баннер) ----------
    if "SSH" in msg or "порту" in msg or "AllowUsers" in msg or "MaxAuthTries" in msg or "баннер" in msg:
        for d in devs:
            info = machines.get(d, {})
            sshd = info.get("sshd", "")
            ban = info.get("banner", "")
            if sshd:
                parts.append("===== " + d + ": sshd -T =====\n" + sshd)
            if ban:
                parts.append("===== " + d + ": файл баннера =====\n" + ban)

    # ---------- sshuser ----------
    if "sshuser" in msg:
        for d in devs:
            info = machines.get(d, {})
            u = info.get("sshuser", "")
            if u:
                parts.append(f"===== {d}: id sshuser + sudo -l -U sshuser =====\n{u}")

    # ---------- net_admin (localdb) ----------
    if "net_admin" in msg:
        for d in devs:
            raw = machines.get(d, {}).get("raw", "")
            blk = _block_until(raw, r"User:\s*net_admin", r"(User:|end$)")
            if not blk:
                found = ", ".join(re.findall(r"User:\s*(\S+)", raw)) or "пусто"
                blk = f"show users localdb -> пользователи: {found}"
            parts.append(f"===== {d}: show users localdb =====\n{blk}")

    # ---------- DHCP ----------
    if "DHCP" in msg:
        raw = machines.get("HQ-RTR", {}).get("raw", "")
        blk = _block_until_bang(raw, r"^dhcp-server\b")
        pool = _block_until_bang(raw, r"^ip pool\b")
        if pool or blk:
            parts.append(f"===== HQ-RTR: DHCP =====\n{pool}\n{blk}".strip())
        for d in devs:
            rt = machines.get(d, {}).get("routes_raw", "")
            if rt and "получил" in msg:
                parts.append(f"===== {d}: ip route =====\n{rt}")
            dns = machines.get(d, {}).get("dns", [])
            if dns and "DNS" in msg:
                parts.append(f"===== {d}: resolv.conf =====\nnameserver " + "\nnameserver ".join(dns))

    # ---------- DNS ----------
    if "DNS" in msg and "разреш" in msg or "пересыл" in msg or "порт 53" in msg:
        for d in devs:
            info = machines.get(d, {})
            dt = info.get("dns_test", "")
            ds = info.get("dns_srv", "")
            if ds:
                parts.append(f"===== {d}: порт 53 =====\n{ds}")
            if dt:
                parts.append(f"===== {d}: DNS TEST (socket) =====\n{dt}")

    # ---------- Часовой пояс ----------
    if "часовой пояс" in msg or "Время" in msg:
        for d in devs:
            info = machines.get(d, {})
            tz = info.get("timezone", "")
            raw = info.get("raw", "")
            if raw and not tz:
                m = re.search(r"^ntp timezone\s+(\S+)", raw, re.M)
                tz = m.group(1) if m else "ntp timezone НЕ задан"
            parts.append(f"===== {d}: timezone =====\n{tz}")

    # ---------- VLAN 999 в пункте 1 (HQ-RTR) ----------
    if "VLAN 999" in msg and "<->" not in msg:
        for d in devs:
            info = machines.get(d, {})
            raw = info.get("raw", "")
            if raw and "RTR" in d:
                for iname in info.get("ifaces", {}):
                    if "999" in iname.lower():
                        blk = _block_until_bang(raw, rf"^interface {re.escape(iname)}\b")
                        if blk:
                            parts.append("===== " + d + ": interface " + iname + " =====\n" + blk)
                        break

    # ---------- Fallback: строки без явного доказательства ----------
    # (например: "VLAN 999 на HQ-RTR не найден", "Стык BR-RTR <-> BR-FW не найден")
    if not parts:
        for d in devs:
            info = machines.get(d, {})
            raw = info.get("raw", "")
            if raw and "RTR" in d:
                blocks = []
                for m in re.finditer(r"^interface\s+(\S+)\n((?: [^\n]*\n?)*)", raw, re.M):
                    ipm = re.search(r"ip address\s+(\S+)", m.group(2))
                    blocks.append("interface " + m.group(1) + ("  -> " + ipm.group(1) if ipm else "  -> без IP"))
                for m in re.finditer(r"^port\s+(\S+)\n((?: [^\n]*\n?)*)", raw, re.M):
                    vlans = re.findall(r"encapsulation dot1q (\d+)", m.group(2))
                    if vlans:
                        blocks.append("port " + m.group(1) + "  -> dot1q: " + ", ".join(vlans))
                if blocks:
                    parts.append("===== " + d + ": фактические интерфейсы =====\n" + "\n".join(blocks))
            elif info.get("ifaces"):
                parts.append("===== " + d + ": ip -br a =====\n" + _iface_lines_linux(info))

    # Дедупликация: убираем повторяющиеся блоки
    seen = set()
    unique_parts = []
    for p in parts:
        first_line = p.split("\n")[0]
        if first_line not in seen:
            seen.add(first_line)
            unique_parts.append(p)
    parts = unique_parts

    if not parts:
        return ""
    joined = "\n\n".join(parts)
    return _highlight(joined, msg)
