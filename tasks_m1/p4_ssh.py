import re

SSH_SERVERS = ("HQ-SRV", "BR-SRV")


def run(machines, var):
    passed, failed = [], []
    exp_port = str(var.SSH_PORT)
    exp_user = var.LINUX_USER.lower()
    exp_tries = str(var.SSH_MAX_TRIES)
    exp_banner = var.SSH_BANNER

    def check(cond, ok_msg, fail_msg):
        (passed if cond else failed).append(ok_msg if cond else fail_msg)

    for dev in SSH_SERVERS:
        sshd = machines.get(dev, {}).get("sshd", "")
        sshd_low = sshd.lower()
        banner = machines.get(dev, {}).get("banner", "").strip()

        m_port = re.search(r"^port\s+(\S+)", sshd_low, re.M)
        act_port = m_port.group(1) if m_port else "не задан"
        check(act_port == exp_port, f"{dev}: SSH работает на порту {exp_port}", f"{dev}: неверный порт SSH (получено '{act_port}', ожидалось '{exp_port}')")

        m_allow = re.search(r"^allowusers\s+(.+)", sshd_low, re.M)
        act_allow = m_allow.group(1).strip() if m_allow else "не задано (разрешены все)"
        allowed_list = act_allow.split()
        check(allowed_list == [exp_user], f"{dev}: доступ разрешен только {var.LINUX_USER} (AllowUsers {var.LINUX_USER})", f"{dev}: неверный AllowUsers (получено '{act_allow}', ожидалось '{var.LINUX_USER}')")

        m_tries = re.search(r"^maxauthtries\s+(\S+)", sshd_low, re.M)
        act_tries = m_tries.group(1) if m_tries else "6 (по умолчанию)"
        check(act_tries == exp_tries, f"{dev}: количество попыток ограничено до {exp_tries} (MaxAuthTries {exp_tries})", f"{dev}: неверный MaxAuthTries (получено '{act_tries}', ожидалось '{exp_tries}')")

        act_ban = banner.replace("\n", " ")[:60] if banner else "пусто / не задан"
        check(exp_banner.lower() in banner.lower(), f"{dev}: баннер '{exp_banner}' настроен", f"{dev}: неверный баннер SSH (получено '{act_ban}', ожидалось '{exp_banner}')")

    return "Пункт 5: Безопасный удаленный доступ (SSH)", passed, failed
