import re

SSH_LINUX_SERVERS = ("HQ-SRV", "BR-SRV")


def run(machines, var):
    passed, failed = [], []
    u = var.LINUX_USER
    uid = var.LINUX_USER_UID
    r_user = var.RTR_USER
    r_role = var.RTR_USER_ROLE

    def check(cond, ok_msg, fail_msg):
        (passed if cond else failed).append(ok_msg if cond else fail_msg)

    for dev in SSH_LINUX_SERVERS:
        uinfo = machines.get(dev, {}).get("sshuser", "")
        lines = uinfo.splitlines()
        first_line = lines.pop(0) if lines else "нет данных"
        expected_id = f"uid={uid}({u})"
        has_uid = expected_id in uinfo
        has_sudo = "nopasswd" in uinfo.lower() and "all" in uinfo.lower()
        check(has_uid, f"{dev}: пользователь {u} создан с UID {uid}", f"{dev}: неверный пользователь/UID (получено: '{first_line}', ожидалось '{expected_id}')")
        check(has_sudo, f"{dev}: sudo без пароля (NOPASSWD: ALL) для {u} настроен", f"{dev}: нет прав NOPASSWD: ALL для {u} (sudo -l: '{uinfo.replace(chr(10), ' ')}')")

    for rtr in ("HQ-RTR", "BR-RTR"):
        raw = machines.get(rtr, {}).get("raw", "")
        m_user = re.search(rf"User:\s*{re.escape(r_user)}\b(.*?)(?:User:|$)", raw, re.S)
        has_admin_role = bool(m_user and re.search(rf"Roles:\s*\n\s*{re.escape(r_role)}\b", m_user.group(1)))
        found_users = ", ".join(re.findall(r"User:\s*(\S+)", raw)) or "нет"
        check(has_admin_role, f"{rtr}: пользователь {r_user} с ролью {r_role} создан", f"{rtr}: пользователь {r_user} (роль {r_role}) не найден (в localdb есть: {found_users})")

    return "Пункт 3: Локальные учетные записи", passed, failed
