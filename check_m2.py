import os
import sys
import subprocess
from tasks_m2.parser import parse_dump
from tasks_m2 import p1_samba, p2_storage_nfs, p4_chrony, p5_ansible, p6_docker_web, p8_dnat_browser
from variants_m2.loader import load_variant

TASKS = {
    "p1": p1_samba,
    "p2_3": p2_storage_nfs,
    "p4": p4_chrony,
    "p5": p5_ansible,
    "p6_7": p6_docker_web,
    "p8_9": p8_dnat_browser,
}


def main():
    var_name = sys.argv[sys.argv.index("--variant") + 1] if "--variant" in sys.argv else None
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    skip_vals = {x for x in (var_name, only) if x}
    args = [a for a in sys.argv[1:] if not a.startswith("-") and a not in skip_vals]

    if not args:
        print("Использование: python3 check_m2.py <ИМЯ_ПУЛА> [--variant default] [--offline]")
        sys.exit(1)

    pool = args.pop(0)
    offline = "--offline" in sys.argv
    var = load_variant(var_name)

    if not offline:
        subprocess.run(["python3", "collector_m2.py", pool, "--variant", var._VARIANT_NAME], check=True)

    dump_file = os.path.join("dumps", pool, f"latest_{pool}.txt")
    if not os.path.isfile(dump_file):
        print(f"Дамп '{dump_file}' не найден.")
        sys.exit(1)

    machines = parse_dump(dump_file)

    print("\n" + "=" * 70)
    print(f"ОТЧЕТ ПО МОДУЛЮ 2 | ПУЛ: {pool} | ВАРИАНТ: {var._VARIANT_NAME}")
    print("=" * 70)

    if not TASKS:
        print("Модули проверки в tasks_m2 пока не подключены — сбор и парсинг прошли успешно!")
        return

    total_ok, total_all = 0, 0
    for key, module in TASKS.items():
        if only and key != only:
            continue
        title, passed, failed = module.run(machines, var)
        total_ok += len(passed)
        total_all += len(passed) + len(failed)
        print(f"\n>>> {title} [{len(passed)}/{len(passed) + len(failed)}]")
        for ok in passed:
            print(f"  [OK]   {ok}")
        for err in failed:
            print(f"  [FAIL] {err}")

    print("\n" + "=" * 70)
    print(f"ОБЩИЙ ИТОГ МОДУЛЯ 2 ({pool}): {total_ok} из {total_all} проверок пройдено.")
    print("=" * 70)


if __name__ == "__main__":
    main()
