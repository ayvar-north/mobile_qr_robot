# Mobile robot — Codex Instructions

## Purpose

This repository implements a Python application for a mobile robot on tracks based on the following hardware:
    - Raspberry Pi 4B
    - Raspberry Pi Pico microcontroller board (based on RP2040 MCU)
    - Waveshare Raspberry Pi Pico motor driver expansion board, suitable for driving two-wheel or four-wheel robots
    - a USB-camera


Read the relevant files in `docs/` before making architectural or behavioral changes.

## Sources of truth

Use these documents in this order:

1. `README.md` — general project description and context.
2. `docs/Pico-Motor-Driver - Waveshare Wiki.html` — motor driver expansion board Wiki for this project.
3. `docs/robot_architecture_ru.md` - software design architechture

## Working rules for Codex

- Inspect the existing implementation before editing.
- Prefer small, reviewable changes over broad rewrites.
- Use modular structure.The code will consist of several independent modules: computer vision module, motor control module (executed on Pico), movement planing module (on Pi), communication module that talks to Pico, smartfone communication module. These modules should be more or less independent on each other.
- use simpe syntax and symple code structure, do not consider all possible edge-cases
- Provide detailed comments in Russian that explain the purpose of the code and what the code should do 