import os
import sys
import glob
import subprocess
from tasks_m1.parser import parse_dump
from tasks_m1 import p1_base, p2_nat, p3_users, p4_ssh, p_services
from variants_m1.loader import load_variant

TASKS = {
    "p1": p1_base,
    "p2": p2_nat,
    "p3": p3_users,
    "p5": p4_ssh,
    "services": p_services,
}


def main():
    var_name = sys.argv[sys.argv.index("--variant") + 1] if "--variant" in sys.argv else None
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    skip_vals = {x for x in (var_name, only) if x}
    args = [a for a in sys.argv[1:] if not a.startswith("-") and a not in skip_vals]

    if not args:
        print("Использование: python3 check.py <ИМЯ_ПУЛА> [--variant default] [-v|--verbose] [--offline] [--only p1|p2|p3|p5|services]")
        sys.exit(1)

    pool = args.pop(0)
    offline = "--offline" in sys.argv
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    var = load_variant(var_name)

    if not offline:
        cmd = ["python3", "collector_m1.py", pool, "latest", "--variant", var._VARIANT_NAME]
        if verbose:
            cmd.append("-v")
        subprocess.run(cmd, check=True)

    files = sorted(glob.glob(os.path.join("dumps", pool, f"*_{pool}.txt")), key=os.path.getmtime)
    if not files:
        print(f"Дампы для пула '{pool}' не найдены.")
        sys.exit(1)

    dump_file = files[-1]
    machines = parse_dump(dump_file)

    print("\n" + "=" * 70)
    print(f"ОТЧЕТ ПО ПРОВЕРКЕ ПУЛА: {pool} | ВАРИАНТ: {var._VARIANT_NAME} (файл: {dump_file})")
    print("=" * 70)

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
    print(f"ОБЩИЙ ИТОГ ПО СТЕНДУ {pool}: {total_ok} из {total_all} проверок пройдено.")
    print("=" * 70)


if __name__ == "__main__":
    main()
