"""Fill these values from the wiring passport before uploading to Pico.

Importing this module never creates hardware objects or starts motors.
"""

# Pico GP20/GP21 -> I2C0 or GP6/GP7 -> I2C1, according to board jumpers.
I2C_ID = None
I2C_SDA_GP = None
I2C_SCL_GP = None
PCA9685_ADDRESS = None
PWM_FREQ_HZ = None  # 50 Hz is only the vendor demo value.

# One of MA, MB, MC, MD for each track. True reverses the physical motor.
LEFT_MOTOR = None
RIGHT_MOTOR = None
LEFT_INVERTED = None
RIGHT_INVERTED = None

# Pico UART pins connected to Pi. Supply verified UART number and GP pins.
UART_ID = None
UART_TX_GP = None
UART_RX_GP = None

# Measured / approved direction change pause and ramp limit.
DIRECTION_DEADTIME_MS = None
RAMP_PCT_PER_S = None

# Conservative software limits. They are not permission for a hardware test.
MAX_PWM_PCT = 30
MAX_STEP_MS = 2000
HB_TIMEOUT_MS = 500


def validate():
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
