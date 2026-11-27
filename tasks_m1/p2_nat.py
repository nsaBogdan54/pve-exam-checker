import re


def run(machines, var=None):
    passed, failed = [], []

    def check(cond, ok_msg, fail_msg):
        (passed if cond else failed).append(ok_msg if cond else fail_msg)

    isp = machines.get("ISP", {})
    fwd_isp = isp.get("ip_forward", "0")
    check(
        fwd_isp == "1",
        "ISP: IP-форвардинг включен (net.ipv4.ip_forward = 1)",
        f"ISP: IP-форвардинг выключен (получено net.ipv4.ip_forward = '{fwd_isp}', ожидалось '1')",
    )

    isp_nat = isp.get("nat", "").lower()
    has_isp_nat = ("masquerade" in isp_nat or "snat" in isp_nat) and ("ens18" in isp_nat or "postrouting" in isp_nat)
    nat_preview = isp.get("nat", "").replace("\n", " | ")[:90] or "пусто"
    check(
        has_isp_nat,
        "ISP: Настроен NAT (MASQUERADE/SNAT) на внешний интерфейс",
        f"ISP: Правило NAT (MASQUERADE/SNAT) не найдено (в таблице: {nat_preview})",
    )

    for rtr in ("HQ-RTR", "BR-RTR"):
        raw = machines.get(rtr, {}).get("raw", "")
        has_outside = "ip nat outside" in raw
        has_inside = "ip nat inside" in raw
        has_overload = bool(re.search(r"ip nat source dynamic inside-to-outside .*overload", raw))

        check(has_outside, f"{rtr}: 'ip nat outside' на внешнем интерфейсе", f"{rtr}: отсутствует 'ip nat outside' в конфиге")
        check(has_inside, f"{rtr}: 'ip nat inside' на внутренних интерфейсах", f"{rtr}: отсутствует 'ip nat inside' в конфиге")
        check(has_overload, f"{rtr}: правило динамического NAT overload настроено", f"{rtr}: не найдено правило 'ip nat source dynamic inside-to-outside ... overload'")

    br_fw = machines.get("BR-FW", {})
    fwd_fw = br_fw.get("ip_forward", "0")
    check(
        fwd_fw == "1",
        "BR-FW: IP-форвардинг включен (net.ipv4.ip_forward = 1)",
        f"BR-FW: IP-форвардинг выключен (получено net.ipv4.ip_forward = '{fwd_fw}', ожидалось '1')",
    )

    return "Пункт 2: Маршрутизация и трансляция адресов (NAT)", passed, failed
