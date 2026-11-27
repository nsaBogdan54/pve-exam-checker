import re
import ipaddress


def run(machines, var):
    passed, failed = [], []

    def check(cond, ok_msg, fail_msg):
        (passed if cond else failed).append(ok_msg if cond else fail_msg)

    hq_srv = machines.get("HQ-SRV", {})
    hq_cli = machines.get("HQ-CLI", {})
    raid = hq_srv.get("raid", "")
    mdadm_det = hq_srv.get("mdadm_detail", "")
    fstab_srv = hq_srv.get("fstab", "")
    mount_srv = hq_srv.get("mount", "")

    # 2.1 RAID 0 на HQ-SRV (/dev/md0 из 2 дисков)
    is_raid0 = ("raid0" in raid.lower() or "raid0" in mdadm_det.lower()) and (var.RAID_DEV in raid)
    m_devs = re.search(r"Active Devices\s*:\s*(\d+)", mdadm_det)
    act_devs = int(m_devs.group(1)) if m_devs else 0
    check(is_raid0 and act_devs >= 2,
          f"HQ-SRV: массив {var.RAID_DEV} ({var.RAID_LEVEL}) собран из {act_devs} дисков",
          f"HQ-SRV: ошибка сборки RAID 0 (устройство {var.RAID_DEV}, активных дисков: {act_devs})")

    # 2.2 Монтирование /raid в ext4 и запись в /etc/fstab
    mounted_ok = (var.RAID_MOUNT in mount_srv) and (var.RAID_FS in mount_srv) and ("NOT_MOUNTED" not in mount_srv)
    check(mounted_ok,
          f"HQ-SRV: массив смонтирован в {var.RAID_MOUNT} ({var.RAID_FS})",
          f"HQ-SRV: {var.RAID_MOUNT} не смонтирован ({mount_srv})")

    fstab_ok = (var.RAID_MOUNT in fstab_srv) and (var.RAID_FS in fstab_srv) and not fstab_srv.strip().startswith("/dev/md0:")
    check(fstab_ok,
          f"HQ-SRV: автомонтирование {var.RAID_MOUNT} прописано в /etc/fstab",
          f"HQ-SRV: некорректная запись в /etc/fstab ('{fstab_srv or 'отсутствует'}')")

    # 3.1 NFS-сервер на HQ-SRV (/raid/nfs rw только для сети HQ-CLI)
    nfs_srv = hq_srv.get("nfs_server", "")
    check("SVC: active" in nfs_srv, "HQ-SRV: служба nfs-server запущена", "HQ-SRV: служба nfs-server не запущена")

    cli_if = next(iter(hq_cli.get("ifaces", {}).values()), None)
    cli_net = cli_if.network if cli_if else None

    export_lines = [l for l in nfs_srv.splitlines() if l.startswith(var.NFS_SHARE)]
    rw_for_cli = False
    world_rw = False
    for line in export_lines:
        if "<world>" in line or "*" in line or "0.0.0.0/0" in line:
            if "rw" in line:
                world_rw = True
            continue
        m_net = re.search(r"\s+(\d+\.\d+\.\d+\.\d+/\d+)\(([^)]+)\)", line)
        if m_net and cli_net:
            exp_net = ipaddress.ip_network(m_net.group(1), strict=False)
            opts = m_net.group(2)
            if "rw" in opts and cli_net.subnet_of(exp_net):
                rw_for_cli = True

    check(rw_for_cli and not world_rw,
          f"HQ-SRV: каталог {var.NFS_SHARE} экспортирован (rw) для сети HQ-CLI ({cli_net})",
          f"HQ-SRV: ошибка экспорта {var.NFS_SHARE} (строки: {' | '.join(export_lines) or 'нет'})")

    # 3.2 Клиент NFS на HQ-CLI (/mnt/nfs)
    nfs_cli = hq_cli.get("nfs_client", "")
    cli_mounted = (var.NFS_CLIENT_MOUNT in nfs_cli) and ("NOT_MOUNTED" not in nfs_cli)
    cli_fstab = "/etc/fstab" in nfs_cli or "/etc/auto" in nfs_cli
    check(cli_mounted,
          f"HQ-CLI: сетевой каталог смонтирован в {var.NFS_CLIENT_MOUNT}",
          f"HQ-CLI: каталог {var.NFS_CLIENT_MOUNT} не смонтирован ({nfs_cli.splitlines() if nfs_cli else 'пусто'})")
    check(cli_fstab,
          f"HQ-CLI: автомонтирование {var.NFS_CLIENT_MOUNT} настроено (fstab/autofs)",
          f"HQ-CLI: не найдена настройка автомонтирования {var.NFS_CLIENT_MOUNT} в fstab/autofs")

    return "Пункты 2 и 3 (М2): Дисковый массив RAID 0 и NFS", passed, failed
