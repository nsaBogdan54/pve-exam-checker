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
    sections = [
        "HOSTNAME", "IP -BR A", "CHRONY SERVER", "DNAT TEST", "CHRONY CLIENT",
        "SOURCES", "RAID", "MDADM DETAIL", "FSTAB", "MOUNT", "MDADM CONF",
        "NFS SERVER", "WEB HQ", "DOMAIN CLIENT", "NFS CLIENT", "BROWSER",
        "SAMBA DC", "ANSIBLE", "ANSIBLE PING", "DOCKER"
    ]
    data = {s.lower().replace(" ", "_").replace("-", "_"): extract_section(body, s) for s in sections}
    data["ifaces"] = {}
    for line in data["ip__br_a"].splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] != "lo":
            ipv4s = [p for p in parts[2:] if "." in p and "/" in p]
            if ipv4s:
                data["ifaces"][parts[0]] = ipaddress.ip_interface(ipv4s[0])
    return data


def parse_ecorouter(body):
    data = {"hostname": "", "ifaces": {}, "raw": body}
    m_host = re.search(r"^hostname\s+(\S+)", body, re.M)
    if m_host:
        data["hostname"] = m_host.group(1).strip()
    for iface_block in re.finditer(r"^interface\s+(\S+)\n((?: [^\n]*\n?)*)", body, re.M):
        iname = iface_block.group(1)
        ibody = iface_block.group(2)
        m_ip = re.search(r"ip address\s+(\d+\.\d+\.\d+\.\d+/\d+)", ibody)
        if m_ip:
            data["ifaces"][iname] = ipaddress.ip_interface(m_ip.group(1))
    return data
