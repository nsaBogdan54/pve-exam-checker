import re


def run(machines, var):
    passed, failed = [], []

    def check(cond, ok_msg, fail_msg):
        (passed if cond else failed).append(ok_msg if cond else fail_msg)

    isp = machines.get("ISP", {})
    isp_ips = {str(ipif.ip) for ipif in isp.get("ifaces", {}).values()}
    chrony_srv = isp.get("chrony_server", "")

    check("SVC: active" in chrony_srv, "ISP: служба chronyd запущена", "ISP: служба chronyd не запущена")
    has_upstream = bool(re.search(r"^(?:pool|server)\s+\S+", chrony_srv, re.M))
    check(has_upstream, "ISP: указан вышестоящий NTP-сервер/пул", "ISP: в /etc/chrony.conf не указан вышестоящий pool/server")

    m_strat = re.search(r"local stratum\s+(\d+)", chrony_srv)
    act_strat = int(m_strat.group(1)) if m_strat else -1
    check(act_strat == var.CHRONY_STRATUM,
          f"ISP: stratum сервера задан равным {act_strat}",
          f"ISP: неверный stratum (получено '{act_strat}', ожидалось '{var.CHRONY_STRATUM}')")

    # Клиенты Linux: HQ-SRV, HQ-CLI, BR-SRV
    for dev in ("HQ-SRV", "HQ-CLI", "BR-SRV"):
        sources = machines.get(dev, {}).get("sources", "")
        synced_isp = any(ip in sources for ip in isp_ips)
        active_src = re.search(r"^\^\*\s+(\S+)", sources, re.M)
        cur_ref = active_src.group(1) if active_src else "нет синхронизации"
        check(synced_isp,
              f"{dev}: синхронизация времени настроена на ISP ({cur_ref})",
              f"{dev}: NTP-клиент не использует ISP (текущий источник: '{cur_ref}')")

    # Клиент EcoRouter: BR-RTR
    br_raw = machines.get("BR-RTR", {}).get("raw", "")
    m_ntp = re.search(r"^ntp server\s+(\S+)", br_raw, re.M)
    rtr_ntp = m_ntp.group(1) if m_ntp else "не задан"
    check(rtr_ntp in isp_ips,
          f"BR-RTR: NTP-сервер указывает на ISP ({rtr_ntp})",
          f"BR-RTR: неверный ntp server (получено '{rtr_ntp}', ожидалось один из {', '.join(sorted(isp_ips))})")

    return "Пункт 4 (М2): Служба сетевого времени Chrony / NTP", passed, failed
