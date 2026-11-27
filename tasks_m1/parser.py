import re
import ipaddress


def parse_dump(filename):
    with open(filename, "r", encoding="utf-8") as f:
        text = f.read()

    blocks = re.split(r"#{70}\nМАШИНА: ([^|]+) \|[^\n]+\n#{70}\n", text)
    machines = {}
    for i in range(1, len(blocks), 2):
        name = blocks[i].strip().upper()
        body = blocks[i + 1]
        machines[name] = parse_ecorouter(body) if "RTR" in name else parse_linux(body)
    return machines


def extract_section(body, header):
    m = re.search(rf"--- {re.escape(header)} ---\n(.*?)(?:\n--- [A-Z0-9_ /.-]+ ---|$)", body, re.S)
    return m.group(1).strip() if m else ""


def parse_linux(body):
    data = {
        "hostname": extract_section(body, "HOSTNAME"),
        "ifaces": {},
        "default_gw": None,
        "routes_raw": extract_section(body, "IP ROUTE"),
        "dns": re.findall(r"nameserver\s+(\S+)", extract_section(body, "RESOLV.CONF")),
        "timezone": extract_section(body, "TIMEZONE"),
        "ip_forward": extract_section(body, "IP_FORWARD") or "0",
        "nat": extract_section(body, "NAT / FIREWALL"),
        "sshuser": extract_section(body, "USER SSHUSER"),
        "sshd": extract_section(body, "SSHD CONFIG"),
        "banner": extract_section(body, "SSH BANNER"),
        "dns_srv": extract_section(body, "DNS SERVER"),
        "dns_test": extract_section(body, "DNS TEST"),
    }

    for line in extract_section(body, "IP -BR A").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] != "lo":
            ipv4s = [p for p in parts[2:] if "." in p and "/" in p]
            if ipv4s:
                data["ifaces"][parts[0]] = ipaddress.ip_interface(ipv4s[0])

    m_gw = re.search(r"default via (\S+)", data["routes_raw"])
    if m_gw:
        data["default_gw"] = m_gw.group(1)
    return data


def parse_ecorouter(body):
    data = {"hostname": "", "ifaces": {}, "default_gw": None, "timezone": "", "raw": body}
    m_host = re.search(r"^hostname\s+(\S+)", body, re.M)
    if m_host:
        data["hostname"] = m_host.group(1).strip()

    m_gw = re.search(r"^ip route 0\.0\.0\.0/0\s+(\S+)", body, re.M)
    if m_gw:
        data["default_gw"] = m_gw.group(1)

    m_tz = re.search(r"^ntp timezone\s+(\S+)", body, re.M)
    if m_tz:
        data["timezone"] = m_tz.group(1).strip()

    for iface_block in re.finditer(r"^interface\s+(\S+)\n((?: [^\n]*\n?)*)", body, re.M):
        iname = iface_block.group(1)
        ibody = iface_block.group(2)
        m_ip = re.search(r"ip address\s+(\d+\.\d+\.\d+\.\d+/\d+)", ibody)
        if m_ip:
            data["ifaces"][iname] = ipaddress.ip_interface(m_ip.group(1))
    return data


def find_link(dev_a, dev_b):
    for if_a, ip_a in dev_a.get("ifaces", {}).items():
        for if_b, ip_b in dev_b.get("ifaces", {}).items():
            if ip_a.network == ip_b.network:
                return (if_a, ip_a), (if_b, ip_b)
    return None, None
