# Параметры Модуля 1 (редактируются под конкретный вариант задания)

# 1. Максимально допустимые маски подсетей (префиксы)
VLAN100_MAX_PREFIX = 27    # HQ-SRV: не более 32 адресов (/27)
VLAN200_MAX_PREFIX = 28    # HQ-CLI: не более 16 адресов (/28)
VLAN999_MAX_PREFIX = 29    # Управление: не более 8 адресов (/29)
BR_FW_RTR_PREFIX = 30      # Стык BR-FW <-> BR-RTR: минимально возможная (/30)
BR_SRV_MAX_PREFIX = 28     # BR-SRV: не более 16 адресов (/28)

# 2. GRE-туннель (Пункт 6)
GRE_SUPERNET = "10.10.10.0/24"
GRE_PREFIX = 30

# 3. Локальные учётные записи (Пункт 3)
LINUX_USER = "sshuser"
LINUX_USER_UID = 2027
LINUX_USER_PASS = "P@ssw0rd"

RTR_USER = "net_admin"
RTR_USER_ROLE = "admin"

# 4. Безопасный удалённый доступ SSH (Пункт 5)
SSH_PORT = "2027"
SSH_MAX_TRIES = "2"
SSH_BANNER = "Authorized access only"
