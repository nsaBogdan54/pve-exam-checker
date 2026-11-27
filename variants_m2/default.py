# Параметры Модуля 2
USER_PREFIX = "hquser"
USER_COUNT = 5
DOMAIN_GROUP = "hq"
PASS_MIN_LEN = 8
LOCKOUT_THRESHOLD = 5
ALLOWED_SUDO_CMDS = ("cat", "grep", "id")

RAID_DEV = "md0"
RAID_LEVEL = "raid0"
RAID_FS = "ext4"
RAID_MOUNT = "/raid"
NFS_SHARE = "/raid/nfs"
NFS_CLIENT_MOUNT = "/mnt/nfs"

CHRONY_STRATUM = 5

ANSIBLE_DIR = "/etc/ansible"
ANSIBLE_HOSTS = ("hq-srv", "hq-cli", "hq-rtr", "br-rtr")

WEB_DB_USER = "web"
WEB_DB_PASS = "P@ssw0rd"
WEB_DB_NAME = "webdb"
DOCKER_PORT = 8080

DNAT_WEB_PORT = 8080
DNAT_SSH_PORT = 2027
