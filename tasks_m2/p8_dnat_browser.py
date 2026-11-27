import re


def _has_dnat(raw, local_ip, local_port, ext_port):
    p1 = rf"ip nat source static tcp\s+{re.escape(local_ip)}\s+{local_port}\s+\S+\s+{ext_port}\b"
    p2 = rf"ip nat destination static tcp\s+\S+\s+{ext_port}\s+{re.escape(local_ip)}\s+{local_port}\b"
    return bool(re.search(p1, raw) or re.search(p2, raw))


def run(machines, var):
    passed, failed = [], []

    def check(cond, ok_msg, fail_msg):
        (passed if cond else failed).append(ok_msg if cond else fail_msg)

    hq_raw = machines.get("HQ-RTR", {}).get("raw", "")
    br_raw = machines.get("BR-RTR", {}).get("raw", "")
    dnat_test = machines.get("ISP", {}).get("dnat_test", "")

    hq_srv_ip = str(next(iter(machines.get("HQ-SRV", {}).get("ifaces", {}).values())).ip) if machines.get("HQ-SRV", {}).get("ifaces") else "192.168"
    br_srv_ip = str(next(iter(machines.get("BR-SRV", {}).get("ifaces", {}).values())).ip) if machines.get("BR-SRV", {}).get("ifaces") else "192.168"

    check(_has_dnat(hq_raw, hq_srv_ip, 80, var.DNAT_WEB_PORT) and ("HQ_WEB: OK" in dnat_test),
          f"Пункт 8 (DNAT): HQ-RTR пробрасывает порт {var.DNAT_WEB_PORT} -> {hq_srv_ip}:80 (доступен с ISP)",
          f"Пункт 8 (DNAT): проброс {var.DNAT_WEB_PORT} на HQ-RTR не настроен или недоступен с ISP")

    check(_has_dnat(hq_raw, hq_srv_ip, var.DNAT_SSH_PORT, var.DNAT_SSH_PORT) and ("HQ_SSH: OK" in dnat_test),
          f"Пункт 8 (DNAT): HQ-RTR пробрасывает SSH порт {var.DNAT_SSH_PORT} -> {hq_srv_ip}:{var.DNAT_SSH_PORT} (доступен с ISP)",
          f"Пункт 8 (DNAT): проброс SSH {var.DNAT_SSH_PORT} на HQ-RTR не настроен или недоступен с ISP")

    check(_has_dnat(br_raw, br_srv_ip, var.DOCKER_PORT, var.DNAT_WEB_PORT) and ("BR_WEB: OK" in dnat_test),
          f"Пункт 8 (DNAT): BR-RTR пробрасывает порт {var.DNAT_WEB_PORT} -> {br_srv_ip}:{var.DOCKER_PORT} (доступен с ISP)",
          f"Пункт 8 (DNAT): проброс {var.DNAT_WEB_PORT} на BR-RTR не настроен или недоступен с ISP")

    check(_has_dnat(br_raw, br_srv_ip, var.DNAT_SSH_PORT, var.DNAT_SSH_PORT) and ("BR_SSH: OK" in dnat_test),
          f"Пункт 8 (DNAT): BR-RTR пробрасывает SSH порт {var.DNAT_SSH_PORT} -> {br_srv_ip}:{var.DNAT_SSH_PORT} (доступен с ISP)",
          f"Пункт 8 (DNAT): проброс SSH {var.DNAT_SSH_PORT} на BR-RTR не настроен или недоступен с ISP")

    browser = machines.get("HQ-CLI", {}).get("browser", "")
    has_browser = "yandex-browser" in browser.lower() and "NO_BROWSER" not in browser
    check(has_browser,
          f"Пункт 9 (Браузер): Яндекс.Браузер установлен на HQ-CLI ({browser.splitlines()})",
          "Пункт 9 (Браузер): Яндекс.Браузер не найден на HQ-CLI")

    return "Пункты 8 и 9 (М2): Статический DNAT и Яндекс.Браузер", passed, failed
