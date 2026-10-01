"""Настройки моторной платы и связи Raspberry Pi Pico с Raspberry Pi.

Номера GP записывайте без приставки GP: для GP20 укажите число 20.
Названия моторных клемм — строки в кавычках; флаги инверсии — True/False
без кавычек. None в обязательном поле запрещает запуск прошивки.
Значения проводки сверяйте с собранным роботом перед моторным испытанием.
"""

# Шина I²C, через которую Pico управляет микросхемой PCA9685.
# Выбранная пара I²C0: SDA на GP20, SCL на GP21. При другой разводке
# согласованно измените все три поля и проверьте положение перемычек платы.
I2C_ID = 0          # Номер шины Pico: 0 для GP20/GP21 или 1 для GP6/GP7.
I2C_SDA_GP = 20     # Контакт Pico, передающий данные I²C.
I2C_SCL_GP = 21     # Контакт Pico, задающий тактовый сигнал I²C.
PCA9685_ADDRESS = 0x40  # Адрес PCA9685 на I²C; сверьте сканированием шины.
PWM_FREQ_HZ = 50        # Общая частота PWM всех моторных каналов, Гц.

# Клеммы моторной платы, к которым подключены левая и правая гусеницы.
# Доступные названия: "MA", "MB", "MC", "MD"; стороны не должны совпадать.
LEFT_MOTOR = "MA"     # Левая гусеница использует каналы PCA9685 0/1/2.
RIGHT_MOTOR = "MB"    # Правая гусеница использует каналы PCA9685 3/4/5.

# Положительный PWM означает движение гусеницы вперёд относительно корпуса.
# Если при короткой проверке на поднятом шасси она идёт назад, поставьте True;
# если вперёд — False. Направления сторон проверяйте по отдельности.
LEFT_INVERTED = False  # Начальное направление левой гусеницы; уточнить на подставке.
RIGHT_INVERTED = False  # Начальное направление правой гусеницы; уточнить на подставке.

# UART передаёт команды между Pi и Pico, независимо от I²C моторной платы.
# TX Pico соединяют с RX Pi, RX Pico — с TX Pi; земля GND общая.
UART_ID = 0           # Номер аппаратного UART Pico.
UART_TX_GP = 0        # Вывод передачи Pico.
UART_RX_GP = 1        # Вывод приёма Pico.
# Пара (TX, RX) должна соответствовать UART_ID; допустимые пары проверяются
# ниже в validate(). Скорость протокола V1 — 115200 бод в main.py и на Pi.

# Начальные параметры для стендовой проверки; при необходимости скорректируйте
# их по фактическому поведению привода. STOP обходит плавное изменение PWM.
DIRECTION_DEADTIME_MS = 20  # Пауза с PWM=0 перед обратным ходом, мс (0–100).
RAMP_PCT_PER_S = 200        # Предельное изменение PWM за секунду, %/с (1–1000).

# Местные пределы Pico: Pi не может увеличить их отдельной командой MOVE.
# PWM — процент воздействия, а не измеренная скорость или расстояние.
MAX_PWM_PCT = 30    # Максимальный модуль PWM одной гусеницы, % (1–100).
MAX_STEP_MS = 2000  # Максимальная длительность одного MOVE, мс (1–2000).
HB_TIMEOUT_MS = 500  # Нет нового HEARTBEAT — выключить привод, мс (100–2000).


def validate():
    """Проверить полноту паспорта и допустимые сочетания пинов/пределов."""
    required = ("I2C_ID", "I2C_SDA_GP", "I2C_SCL_GP", "PCA9685_ADDRESS",
                "PWM_FREQ_HZ", "LEFT_MOTOR", "RIGHT_MOTOR",
                "LEFT_INVERTED", "RIGHT_INVERTED", "UART_ID",
                "UART_TX_GP", "UART_RX_GP", "DIRECTION_DEADTIME_MS",
                "RAMP_PCT_PER_S")
    missing = [name for name in required if globals()[name] is None]
    if missing:
        raise ValueError("unfilled wiring passport: " + ", ".join(missing))
    if (I2C_ID, I2C_SDA_GP, I2C_SCL_GP) not in ((0, 20, 21), (1, 6, 7)):
        raise ValueError("unsupported I2C jumper/pin combination")
    if not (0x40 <= PCA9685_ADDRESS <= 0x5f):
        raise ValueError("PCA9685 address")
    if not (24 <= PWM_FREQ_HZ <= 1526):
        raise ValueError("PCA9685 PWM frequency")
    if LEFT_MOTOR not in ("MA", "MB", "MC", "MD") or RIGHT_MOTOR not in ("MA", "MB", "MC", "MD") or LEFT_MOTOR == RIGHT_MOTOR:
        raise ValueError("motor terminal mapping")
    if type(LEFT_INVERTED) is not bool or type(RIGHT_INVERTED) is not bool:
        raise ValueError("motor inversion must be bool")
    uart_pins = {0: ((0, 1), (12, 13), (16, 17)),
                 1: ((4, 5), (8, 9))}
    if UART_ID not in uart_pins or (UART_TX_GP, UART_RX_GP) not in uart_pins[UART_ID]:
        raise ValueError("UART pins")
    if not (0 <= DIRECTION_DEADTIME_MS <= 100 and 1 <= RAMP_PCT_PER_S <= 1000):
        raise ValueError("direction pause or ramp")
    if not (1 <= MAX_PWM_PCT <= 100 and 1 <= MAX_STEP_MS <= 2000 and 100 <= HB_TIMEOUT_MS <= 2000):
        raise ValueError("software limits")
