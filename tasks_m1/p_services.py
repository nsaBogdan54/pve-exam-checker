import re
import ipaddress


def run(machines, var):
    passed, failed = [], []

    def check(cond, ok_msg, fail_msg):
        (passed if cond else failed).append(ok_msg if cond else fail_msg)

    hq_rtr = machines.get("HQ-RTR", {})
    hq_raw = hq_rtr.get("raw", "")

    # Пункт 4: VLAN 100, 200, 999 на одном физическом порту HQ-RTR
    vlan_ports = {}
    for port_block in re.finditer(r"^port\s+(\S+)\n((?: [^\n]*\n?)*)", hq_raw, re.M):
        pname = port_block.group(1)
        pbody = port_block.group(2)
        vlans = re.findall(r"encapsulation dot1q (\d+)", pbody)
        if vlans:
            vlan_ports[pname] = set(vlans)

    one_port_ok = any({"100", "200", "999"}.issubset(v) for v in vlan_ports.values())
    check(one_port_ok, "Пункт 4 (VLAN): VLAN 100, 200, 999 настроены на одном порту HQ-RTR", "Пункт 4 (VLAN): не найдены все три VLAN (100, 200, 999) на одном порту HQ-RTR")

    # Пункт 6: GRE-туннель в сети 10.10.10.0/24 с минимальной маской (/30)
    for rtr in ("HQ-RTR", "BR-RTR"):
        raw = machines.get(rtr, {}).get("raw", "")
        tun = machines.get(rtr, {}).get("ifaces", {}).get("tunnel.0")
        m_tun = re.search(r"^interface tunnel\.0\n((?: [^\n]*\n?)*)", raw, re.M)
        has_gre = bool(m_tun and "mode gre" in m_tun.group(1))
        in_10 = bool(tun and tun.network.subnet_of(ipaddress.ip_network(var.GRE_SUPERNET)))
        is_30 = bool(tun and tun.network.prefixlen == var.GRE_PREFIX)
        check(has_gre and in_10 and is_30,
              f"Пункт 6 (GRE): {rtr} tunnel.0 ({tun}) настроен в режиме GRE с маской /{var.GRE_PREFIX}",
              f"Пункт 6 (GRE): {rtr} ошибка в настройке GRE-туннеля или маске ({tun}, нужно /{var.GRE_PREFIX} из {var.GRE_SUPERNET})")

    # Пункт 7: OSPF + MD5 аутентификация + маршруты на BR-FW
    for rtr in ("HQ-RTR", "BR-RTR"):
        raw = machines.get(rtr, {}).get("raw", "")
        has_ospf = "router ospf" in raw
        has_md5 = "ip ospf message-digest-key" in raw and "md5" in raw
        check(has_ospf, f"Пункт 7 (OSPF): на {rtr} запущен OSPF", f"Пункт 7 (OSPF): на {rtr} не настроен OSPF")
        check(has_md5, f"Пункт 7 (OSPF): на {rtr} включена MD5-аутентификация", f"Пункт 7 (OSPF): на {rtr} не найдена MD5-аутентификация OSPF")

    br_fw_routes = machines.get("BR-FW", {}).get("routes_raw", "")
    check("proto ospf" in br_fw_routes, "Пункт 7 (OSPF): BR-FW получает маршруты по OSPF", "Пункт 7 (OSPF): в таблице маршрутизации BR-FW нет маршрутов OSPF")

    # Пункт 9: DHCP на HQ-RTR и получение адреса HQ-CLI
    hq_srv_ip = str(machines.get("HQ-SRV", {}).get("ifaces", {}).get("ens18", "").ip) if machines.get("HQ-SRV", {}).get("ifaces", {}).get("ens18") else ""
    hq_rtr_vl200_ip = str(hq_rtr.get("ifaces", {}).get("vl200", "").ip) if hq_rtr.get("ifaces", {}).get("vl200") else ""
    has_dhcp_srv = "dhcp-server" in hq_raw and (hq_srv_ip in hq_raw) and (hq_rtr_vl200_ip in hq_raw) and ("au-team.irpo" in hq_raw)
    check(has_dhcp_srv, "Пункт 9 (DHCP): на HQ-RTR настроен DHCP-сервер (шлюз, DNS HQ-SRV, домен au-team.irpo)", "Пункт 9 (DHCP): неполные параметры DHCP на HQ-RTR")

    hq_cli = machines.get("HQ-CLI", {})
    check("proto dhcp" in hq_cli.get("routes_raw", ""), "Пункт 9 (DHCP): HQ-CLI получил параметры по DHCP", "Пункт 9 (DHCP): на HQ-CLI не видно маршрута от DHCP")
    check(hq_srv_ip in hq_cli.get("dns", []), f"Пункт 9 (DHCP): HQ-CLI получил DNS {hq_srv_ip}", f"Пункт 9 (DHCP): в resolv.conf на HQ-CLI ({hq_cli.get('dns')}) нет DNS {hq_srv_ip}")

    # Пункт 10: DNS-сервер на HQ-SRV и разрешение имен (A, PTR, внешние домены)
    dns_srv = machines.get("HQ-SRV", {}).get("dns_srv", "")
    check(":53" in dns_srv, "Пункт 10 (DNS): DNS-сервер на HQ-SRV слушает порт 53", "Пункт 10 (DNS): DNS-сервер на HQ-SRV не слушает порт 53")

    all_6_hosts = (
        "hq-rtr.au-team.irpo",
        "hq-srv.au-team.irpo",
        "hq-cli.au-team.irpo",
        "br-rtr.au-team.irpo",
        "br-fw.au-team.irpo",
        "br-srv.au-team.irpo",
    )
    for client in ("HQ-SRV", "HQ-CLI", "BR-SRV"):
        dtest = machines.get(client, {}).get("dns_test", "")
        m_a = re.search(r"^A:\s*(\{.*\})", dtest, re.M)
        a_dict_str = m_a.group(1) if m_a else ""
        missing_hosts = [h for h in all_6_hosts if f"'{h}'" not in a_dict_str]
        a_ok = bool(a_dict_str) and not missing_hosts
        ptr_ok = "PTR_HQ: ('hq-srv.au-team.irpo'" in dtest and "PTR_BR: ('br-srv.au-team.irpo'" in dtest
        ext_ok = "EXT: " in dtest
        fail_detail = ", ".join(missing_hosts) if missing_hosts else (dtest.splitlines()[0] if dtest else "нет ответа")
        check(a_ok, f"Пункт 10 (DNS): с {client} работают прямые (A) записи всех 6 узлов", f"Пункт 10 (DNS): с {client} не резолвятся A-записи: {fail_detail}")
        check(ptr_ok, f"Пункт 10 (DNS): с {client} работают обратные (PTR) записи для hq-srv и br-srv", f"Пункт 10 (DNS): ошибка обратных (PTR) записей hq-srv/br-srv с {client}")
        check(ext_ok, f"Пункт 10 (DNS): с {client} работает пересылка внешних доменов (ya.ru)", f"Пункт 10 (DNS): не работает пересылка внешних доменов с {client}")

    # Пункт 11: Часовой пояс
    expected_tz = machines.get("ISP", {}).get("timezone", "")
    for dev in ("ISP", "HQ-SRV", "HQ-CLI", "BR-FW", "BR-SRV"):
        tz = machines.get(dev, {}).get("timezone", "")
        check(bool(tz) and tz == expected_tz, f"Пункт 11 (Время): {dev} часовой пояс {tz}", f"Пункт 11 (Время): {dev} часовой пояс '{tz}' отличается от '{expected_tz}'")

    for rtr in ("HQ-RTR", "BR-RTR"):
        tz = machines.get(rtr, {}).get("timezone", "")
        check(bool(tz), f"Пункт 11 (Время): {rtr} часовой пояс задан ({tz})", f"Пункт 11 (Время): на {rtr} не задан ntp timezone")

    return "Пункты 4, 6, 7, 9, 10, 11: Сетевые службы, DNS и время", passed, failed
