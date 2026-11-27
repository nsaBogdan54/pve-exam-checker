import re


def run(machines, var):
    passed, failed = [], []

    def check(cond, ok_msg, fail_msg):
        (passed if cond else failed).append(ok_msg if cond else fail_msg)

    br = machines.get("BR-SRV", {})
    inv = br.get("ansible", "")
    ping_out = br.get("ansible_ping", "")

    check("NO_ANSIBLE_DIR" not in inv,
          f"BR-SRV: рабочий каталог {var.ANSIBLE_DIR} существует",
          f"BR-SRV: каталог {var.ANSIBLE_DIR} не найден")

    inv_low = inv.lower()
    missing_inv = [h for h in var.ANSIBLE_HOSTS if h.lower() not in inv_low]
    check(not missing_inv,
          f"BR-SRV: все 4 узла ({', '.join(var.ANSIBLE_HOSTS)}) есть в инвентаре Ansible",
          f"BR-SRV: в инвентаре Ansible отсутствуют хосты: {', '.join(missing_inv)}")

    pong_ok = []
    pong_fail = []
    for h in var.ANSIBLE_HOSTS:
        if re.search(rf"{re.escape(h)}\s*\|\s*SUCCESS.*\"ping\":\s*\"pong\"", ping_out, re.I | re.S):
            pong_ok.append(h)
        else:
            pong_fail.append(h)

    check(not pong_fail and len(pong_ok) == len(var.ANSIBLE_HOSTS),
          f"BR-SRV: команда 'ansible all -m ping' вернула pong от всех узлов ({', '.join(pong_ok)})",
          f"BR-SRV: нет ответа pong в Ansible от узлов: {', '.join(pong_fail)}")

    return "Пункт 5 (М2): Система управления конфигурациями Ansible", passed, failed
