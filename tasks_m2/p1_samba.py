import re


def run(machines, var):
    passed, failed = [], []

    def check(cond, ok_msg, fail_msg):
        (passed if cond else failed).append(ok_msg if cond else fail_msg)

    br = machines.get("BR-SRV", {})
    cli = machines.get("HQ-CLI", {})
    samba = br.get("samba_dc", "")
    dom_cli = cli.get("domain_client", "")

    check("SVC: active" in samba, "BR-SRV: служба Samba DC активна", "BR-SRV: служба Samba DC не запущена")

    m_len = re.search(r"Minimum password length:\s*(\d+)", samba)
    act_len = int(m_len.group(1)) if m_len else -1
    check(act_len >= var.PASS_MIN_LEN,
          f"BR-SRV: минимальная длина пароля {act_len} (>= {var.PASS_MIN_LEN})",
          f"BR-SRV: неверная длина пароля (получено '{act_len}', нужно >= {var.PASS_MIN_LEN})")

    m_lock = re.search(r"Account lockout threshold.*?:\s*(\d+)", samba)
    act_lock = int(m_lock.group(1)) if m_lock else 0
    check(0 < act_lock <= var.LOCKOUT_THRESHOLD,
          f"BR-SRV: порог блокировки учётной записи {act_lock} попыток",
          f"BR-SRV: неверный порог блокировки (получено '{act_lock}', нужно 1..{var.LOCKOUT_THRESHOLD})")

    m_users = re.search(r"^USERS:\s*(.+)$", samba, re.M)
    users_set = set(m_users.group(1).split()) if m_users else set()
    m_grp = re.search(r"^GRP_MEMBERS:\s*(.+)$", samba, re.M)
    grp_set = set(m_grp.group(1).split()) if m_grp else set()

    expected_users = [f"{var.USER_PREFIX}{i}" for i in range(1, var.USER_COUNT + 1)]
    missing_users = [u for u in expected_users if u not in users_set]
    missing_in_grp = [u for u in expected_users if u not in grp_set]

    check(not missing_users,
          f"BR-SRV: все {var.USER_COUNT} пользователей ({', '.join(expected_users)}) созданы",
          f"BR-SRV: отсутствуют пользователи в домене: {', '.join(missing_users)}")
    check(not missing_in_grp,
          f"BR-SRV: все пользователи добавлены в группу '{var.DOMAIN_GROUP}'",
          f"BR-SRV: не добавлены в группу '{var.DOMAIN_GROUP}': {', '.join(missing_in_grp)}")

    dom_low = dom_cli.lower()
    in_domain = ("au-team.irpo" in dom_low and "kerberos-member" in dom_low) or ("join is ok" in dom_low) or ("succeeded" in dom_low)
    check(in_domain, "HQ-CLI: машина введена в домен au-team.irpo", "HQ-CLI: машина не введена в домен au-team.irpo")

    u1 = f"{var.USER_PREFIX}1"
    grp_visible = f"({u1})" in dom_low and (f"({var.DOMAIN_GROUP})" in dom_low or f"{var.DOMAIN_GROUP}:" in dom_low)
    check(grp_visible,
          f"HQ-CLI: доменный пользователь {u1} и группа '{var.DOMAIN_GROUP}' распознаются системой",
          f"HQ-CLI: пользователь {u1} или группа '{var.DOMAIN_GROUP}' не видны в NSS")

    m_sudo = re.search(r"SUDO_USER:\s*(.+)", dom_cli)
    sudo_out = m_sudo.group(1) if m_sudo else ""
    allowed_part = sudo_out.split("may run the following commands")[-1] if "may run the following commands" in sudo_out else sudo_out
    has_all_cmds = bool(re.search(r"\)\s*(?:NOPASSWD:\s*)?ALL\b", allowed_part))
    found_cmds = [c for c in var.ALLOWED_SUDO_CMDS if re.search(rf"/(?:usr/)?bin/{re.escape(c)}\b", allowed_part)]
    missing_cmds = [c for c in var.ALLOWED_SUDO_CMDS if c not in found_cmds]

    check(not has_all_cmds and not missing_cmds,
          f"HQ-CLI: права sudo ограничены командами {', '.join(var.ALLOWED_SUDO_CMDS)}",
          f"HQ-CLI: ошибка прав sudo для {u1} (получено: '{allowed_part.strip()}', нужно только {', '.join(var.ALLOWED_SUDO_CMDS)})")

    return "Пункт 1 (М2): Контроллер домена Samba DC и права sudo", passed, failed
