import re


def run(machines, var):
    passed, failed = [], []

    def check(cond, ok_msg, fail_msg):
        (passed if cond else failed).append(ok_msg if cond else fail_msg)

    # --- Пункт 6: Docker на BR-SRV ---
    br = machines.get("BR-SRV", {})
    dock = br.get("docker", "")

    check("SVC: active" in dock, "Пункт 6 (Docker): служба docker на BR-SRV активна", "Пункт 6 (Docker): служба docker не запущена")

    m_ps = re.search(r"^PS:\s*(.+)$", dock, re.M)
    ps_str = m_ps.group(1) if m_ps else ""
    has_site = "site" in ps_str.lower() and "up" in ps_str.lower()
    has_db = "mariadb" in ps_str.lower() and "up" in ps_str.lower()
    check(has_site and has_db,
          "Пункт 6 (Docker): контейнеры веб-приложения (site) и БД (mariadb) запущены",
          f"Пункт 6 (Docker): не запущены нужные контейнеры (docker ps: '{ps_str or 'пусто'}')")

    m_comp = re.search(r"^COMPOSE:\s*(.+)$", dock, re.M)
    comp_path = m_comp.group(1).strip() if m_comp else ""
    check(bool(comp_path),
          f"Пункт 6 (Docker): файл compose найден ({comp_path})",
          "Пункт 6 (Docker): файл compose.yaml не найден")

    port_ok = f"HTTP_{var.DOCKER_PORT}: 200" in dock
    check(port_ok,
          f"Пункт 6 (Docker): приложение testapp отвечает HTTP 200 на порту {var.DOCKER_PORT}",
          f"Пункт 6 (Docker): приложение testapp не отвечает на порту {var.DOCKER_PORT}")

    # --- Пункт 7: Web-приложение на HQ-SRV (Apache + MariaDB) ---
    hq = machines.get("HQ-SRV", {})
    web = hq.get("web_hq", "")

    check("APACHE: active" in web, "Пункт 7 (Web HQ): веб-сервер Apache запущен", "Пункт 7 (Web HQ): веб-сервер Apache не запущен")
    check("MARIADB: active" in web, "Пункт 7 (Web HQ): СУБД MariaDB запущена", "Пункт 7 (Web HQ): СУБД MariaDB не запущена")

    db_ok = "employees" in web.lower() and "access denied" not in web.lower() and "tables_in_" in web.lower()
    check(db_ok,
          f"Пункт 7 (Web HQ): БД '{var.WEB_DB_NAME}' импортирована и доступна пользователю '{var.WEB_DB_USER}'",
          f"Пункт 7 (Web HQ): ошибка доступа или пустая БД '{var.WEB_DB_NAME}'")

    has_files = "index.php" in web and "logo.png" in web
    check(has_files,
          "Пункт 7 (Web HQ): файлы index.php и logo.png размещены в корне сайта",
          "Пункт 7 (Web HQ): отсутствуют index.php или logo.png в /var/www")

    http_ok = "HTTP_CODE: 200" in web and "HAS_ERROR: False" in web
    check(http_ok,
          "Пункт 7 (Web HQ): сайт на HQ-SRV открывается (HTTP 200) без ошибок подключения к БД",
          "Пункт 7 (Web HQ): сайт на HQ-SRV недоступен или возвращает ошибку БД")

    return "Пункты 6 и 7 (М2): Веб-приложения (Docker на BR-SRV и LAMP на HQ-SRV)", passed, failed
