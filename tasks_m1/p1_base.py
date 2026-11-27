from tasks_m1.parser import find_link

EXPECTED_HOSTNAMES = {
    "HQ-RTR": "hq-rtr.au-team.irpo",
    "HQ-SRV": "hq-srv.au-team.irpo",
    "HQ-CLI": "hq-cli.au-team.irpo",
    "BR-RTR": "br-rtr.au-team.irpo",
    "BR-FW": "br-fw.au-team.irpo",
    "BR-SRV": "br-srv.au-team.irpo",
}


def run(machines, var):
    passed, failed = [], []

    def check(cond, ok_msg, fail_msg):
        (passed if cond else failed).append(ok_msg if cond else fail_msg)

    for dev, exp_fqdn in EXPECTED_HOSTNAMES.items():
        actual = machines.get(dev, {}).get("hostname", "<отсутствует>")
        check(actual == exp_fqdn, f"FQDN {dev}: {actual}", f"FQDN {dev}: '{actual}' != '{exp_fqdn}'")

    for dev, info in machines.items():
        for iface, ip_if in info.get("ifaces", {}).items():
            if dev == "ISP" and iface == "ens18":
                continue
            check(ip_if.ip.is_private, f"Приватный IP {dev} ({iface}): {ip_if}", f"Неприватный IP {dev} ({iface}): {ip_if}")

    a, b = find_link(machines.get("HQ-RTR", {}), machines.get("HQ-SRV", {}))
    if a and b:
        p100 = var.VLAN100_MAX_PREFIX
        check(a[1].network.prefixlen >= p100, f"VLAN 100: {a[1]} <-> {b[1]} (/{a[1].network.prefixlen} >= /{p100})", f"VLAN 100: маска /{a[1].network.prefixlen} шире допустимой /{p100}")
        check(machines["HQ-SRV"].get("default_gw") == str(a[1].ip), f"Шлюз HQ-SRV -> {a[1].ip}", f"Шлюз HQ-SRV не на {a[1].ip}")
    else:
        failed.append("Стык VLAN 100 (HQ-RTR <-> HQ-SRV) не найден")

    a, b = find_link(machines.get("HQ-RTR", {}), machines.get("HQ-CLI", {}))
    if a and b:
        p200 = var.VLAN200_MAX_PREFIX
        check(a[1].network.prefixlen >= p200, f"VLAN 200: {a[1]} <-> {b[1]} (/{a[1].network.prefixlen} >= /{p200})", f"VLAN 200: маска /{a[1].network.prefixlen} шире допустимой /{p200}")
        check(machines["HQ-CLI"].get("default_gw") == str(a[1].ip), f"Шлюз HQ-CLI -> {a[1].ip}", f"Шлюз HQ-CLI не на {a[1].ip}")
    else:
        failed.append("Стык VLAN 200 (HQ-RTR <-> HQ-CLI) не найден")

    hq_rtr_ifaces = machines.get("HQ-RTR", {}).get("ifaces", {})
    vl999 = None
    for iname, ipif in hq_rtr_ifaces.items():
        if iname in ("tunnel.0", "isp"):
            continue
        if "999" in iname.lower():
            vl999 = ipif
            break
        if ipif.network.prefixlen >= var.VLAN999_MAX_PREFIX:
            vl999 = ipif
    if vl999:
        p999 = var.VLAN999_MAX_PREFIX
        check(vl999.network.prefixlen >= p999, f"VLAN 999 на HQ-RTR: {vl999} (/{vl999.network.prefixlen} >= /{p999})", f"VLAN 999 на HQ-RTR: маска /{vl999.network.prefixlen} шире допустимой /{p999}")
    else:
        failed.append("VLAN 999 на HQ-RTR не найден")

    a, b = find_link(machines.get("BR-RTR", {}), machines.get("BR-FW", {}))
    if a and b:
        pfw = var.BR_FW_RTR_PREFIX
        check(a[1].network.prefixlen == pfw and b[1].network.prefixlen == pfw, f"Стык BR-RTR <-> BR-FW: {a[1]} <-> {b[1]} (/{pfw})", f"Стык BR-RTR <-> BR-FW: маска /{a[1].network.prefixlen} != /{pfw}")
        check(machines["BR-FW"].get("default_gw") == str(a[1].ip), f"Шлюз BR-FW -> {a[1].ip}", f"Шлюз BR-FW не на {a[1].ip}")
    else:
        failed.append("Стык BR-RTR <-> BR-FW не найден")

    a, b = find_link(machines.get("BR-FW", {}), machines.get("BR-SRV", {}))
    if a and b:
        psrv = var.BR_SRV_MAX_PREFIX
        check(a[1].network.prefixlen >= psrv, f"Сеть BR-FW <-> BR-SRV: {a[1]} <-> {b[1]} (/{a[1].network.prefixlen} >= /{psrv})", f"Сеть BR-FW <-> BR-SRV: маска /{a[1].network.prefixlen} шире допустимой /{psrv}")
        check(machines["BR-SRV"].get("default_gw") == str(a[1].ip), f"Шлюз BR-SRV -> {a[1].ip}", f"Шлюз BR-SRV не на {a[1].ip}")
    else:
        failed.append("Стык BR-FW <-> BR-SRV не найден")

    for rtr in ("HQ-RTR", "BR-RTR"):
        a, b = find_link(machines.get("ISP", {}), machines.get(rtr, {}))
        if a and b:
            check(machines[rtr].get("default_gw") == str(a[1].ip), f"Внешний линк ISP <-> {rtr}: {a[1]} <-> {b[1]}", f"Шлюз {rtr} не на {a[1].ip}")
        else:
            failed.append(f"Внешний линк ISP <-> {rtr} не найден")

    return "Пункт 1: Базовая настройка и IPv4", passed, failed
