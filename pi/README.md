# Программа Raspberry Pi

Код в `robot/` следует карте модулей §3.1 `docs/robot_architecture_ru.md`.

## Что делает каждый модуль

| Модуль | Назначение |
|---|---|
| `config`, `types` | Проверяют конфигурацию и задают неизменяемые структуры обмена. |
| `vision.capture`, `vision.decoder`, `vision.worker` | Читают USB-камеру и распознают QR в отдельном процессе. Очереди сохраняют только свежий кадр и пакет наблюдений; STOP также передаётся отдельным флагом. |
| `qr.schema`, `qr.gate` | Проверяют JSON карточки, три свежих предъявления, снятие карточки и приоритет STOP. |
| `planning`, `execution` | Переводят действие в конечные PWM/время и исполняют маршрут по одному MOVE, дожидаясь DONE. |
| `transport.codec`, `transport.serial_client` | Проверяют кадры V1/CRC; только клиент открывает UART, создаёт сеанс и повторяет запрос с прежним SEQ. |
| `controller`, `supervisor`, `telemetry` | Держат режим и разрешение, прерывают маршрут по STOP/сбою, контролируют свежесть и публикуют статус. |
| `remote.local_api`, `remote.cli` | Принимают ограниченные команды по Unix-сокету; `robotctl` обращается к уже работающему `robotd`. |
| `remote.bluetooth` | Адаптер команд из доверенного RFCOMM-потока к тому же локальному API. Регистрация BlueZ-профиля и проверка доверенного устройства остаются задачей развёртывания Bluetooth после базового Wi-Fi. |
| `bootstrap` | Запускает компоненты, повторяет подключение устройств и делает STOP при завершении процесса. |

## Проверка без моторов

Из корня репозитория:

```sh
PYTHONPATH=pi python -m unittest discover -s tests -v
PYTHONPATH=pi python -m robot.bootstrap --config config/pi.dry-run.json
PYTHONPATH=pi python -m robot.remote.cli --socket /tmp/qr-robot-control.sock status
PYTHONPATH=pi python -m robot.remote.cli --socket /tmp/qr-robot-control.sock start --mode manual
PYTHONPATH=pi python -m robot.remote.cli --socket /tmp/qr-robot-control.sock move --action forward --pwm 20 --duration-ms 200
PYTHONPATH=pi python -m robot.remote.cli --socket /tmp/qr-robot-control.sock stop
```

`dry_run=true` создаёт `FakePicoTransport`, который совсем не открывает UART. Команда `start --mode qr` требует настоящих свежих кадров и поэтому без камеры будет отклонена. Для SSH/RaspController используются те же команды `robotctl` после установки пакета `pi/`.

## Аппаратный режим

`config/pi.hardware.example.json` намеренно содержит `null` для непроверенных устройств и `hardware_verified=false`. Сначала заполните паспорт проводки и профиль камеры, затем укажите фактические пути `/dev/...` и только после аппаратной проверки поставьте `hardware_verified=true`. В таком режиме Pi использует GPIO UART, а не USB REPL Pico. Начальные лимиты 30% PWM и 2000 мс — проектные пределы, не результаты испытания.

Профили `turn_around` по умолчанию пусты. Каждый профиль требует `profile_id`, `direction` (`left`/`right`), `pwm_pct`, `duration_ms`, `verified`, `tested_at` и `conditions`. Непроверенный профиль не запускает движение. Энкодеры и вычисленные из PWM скорость/путь в этой версии отсутствуют.

Локальный сокет имеет права `0660`. Для `/run/qr-robot/control.sock` каталог должен заранее создать systemd (`RuntimeDirectory=qr-robot`) с нужным пользователем/группой. Вторая копия `robotd` отклоняется блокировкой рядом с сокетом. Автозапуск, точка доступа Wi-Fi и BlueZ-профиль не включаются автоматически этим кодом; их настройка требует аппаратной и стендовой приёмки из архитектуры.

Свежесть кадра оценивается по метке после `VideoCapture.read()`, непрерывному чтению и буферу размером один кадр. Это не доказывает задержку внутри конкретной USB-камеры: перед использованием QR для движения её нужно измерить на выбранном разрешении и FPS. Проверки выше не заменяют испытание реального UART, камеры, направлений гусениц и времени остановки.
