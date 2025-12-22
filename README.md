# GameAgent – Scriptable Image Automation Tool for Game Daily Tasks
 🎮

GameAgent is a modular, image-based automation framework for mobile games and emulators.

You can automate daily sign-in, rewards collection, and repetitive tasks **without modifying game files** — simply by using images and command scripts.

---

## ✨ Features

- 🖼️ Image-based automation (no memory hacking)
- 📜 Simple command script (`commands.txt`)
- 🧩 Modular: one folder per game
- 🔄 OCR support (captcha / text detection)
- ⏸️ Pause & resume execution
- 🧵 Parallel execution support

auto script basic on pyautogy and tesseract

can input name or index to execute the script

---


## 🚀 Quick Start

Python ≥ 3.8  
pyautogui  
pytesseract  
opencv-python 

Run the main script

## 📁 Project Structure

GameAgent/
├─ main.py
├─ games/
│ ├─ gamefolder/
│ │ ├─ commands.txt
│ │ ├─ home.png
│ │ └─ battle.png
│ └─ game2folder/
│ ├─ commands.txt
│ └─ login.png


Each game folder contains:
- `commands.txt` – automation script
- `.png` images – UI elements to detect

## 📝 Command Script Syntax

### ▶ Flow Control

| Symbol | Description |
|---|---|
| `↑` | Shorten image wait time, retry previous step if not detected |
| `?` | Shorten image wait time, skip to next step if not detected |
| `|` | Enable parallel execution |
| `*-*->*` | Conditional execution |

---

### ▶ Wait / Detection

| Command | Description |
|---|---|
| `waitImg` | Wait until an image appears |
| `waitPress` | Wait for keyboard input |
| `waitMouse` | Wait for mouse input |
| `wait1` | Wait 1 second (supports decimal) |

---

### ▶ Input / Actions

| Command | Description |
|---|---|
| `press` | Press a keyboard key |
| `mouseClick` | Left mouse click |
| `mouseMove(x_y)` | Move mouse to coordinates |
| `scrollUp` / `scrollDown` | Mouse wheel scroll |

---

### ▶ Special

| Command | Description |
|---|---|
| `"text"` | Type alphanumeric text |
| `@` | OCR captcha input |
| `#` | specific the index if pictures in screen have multiple
| `http://` | Open URL |
| `.lnk` | Execute shortcut via cmd |

---

exsample:
daily:{quest,wait1,subQuest,wait1,evolveQuest,wait1,evolve2@II,confirm,wait1,auto,wait1,skip#2,max,wait1,ok,toQuest}



## ⚠ Disclaimer

This project is for **educational and personal use only**.
Use at your own risk. The author is not responsible for any account bans.

---

## 📜 License

Apache License 2.0



