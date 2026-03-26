GameAgent is an image-based automation system for PC games, emulators, and mobile games running on desktop environments.
It allows you to automate daily sign-ins, reward collection, and repetitive tasks without modifying game files or memory.

The system is designed to be easy to use even with no programming background — simply prepare images and a command script, and GameAgent handles the rest.

Core Concept

GameAgent uses image recognition instead of fixed screen coordinates.
You create automation scripts by:

Creating a folder for each game

Adding reference images (buttons, icons, UI elements)

Writing simple command instructions in a script file

This modular design greatly reduces duplicated work when creating or maintaining scripts.

Key Advantages Over Traditional Game Scripts
1️⃣ Image-based Clicking (No Strict Window Positioning)

Clicks are performed based on matching images, not absolute coordinates

You don’t need to lock the game window to an exact position

As long as the window aspect ratio matches the screenshot, the script remains stable

2️⃣ OCR Verification for Accurate Actions

Optional OCR text recognition ensures the correct button is clicked

Useful when the same UI element appears in different contexts
(e.g., multiple stages using the same background)

Example: only click an image if the detected text contains “Lv.7”

3️⃣ Multi-Image Detection Logic

Supports simultaneous detection of multiple images

You can configure actions such as:

“Click when any one of these images appears”

Ideal for handling branching UI states, popups, or random events

Features

✨ Image-based automation (no memory hacking)
📜 Simple script commands (commands.txt)
🧩 Modular structure (one folder per game)
🔄 OCR support (text & captcha detection)
⏸️ Pause and resume execution
🧵 Parallel execution support
⚙️ Built with PyAutoGUI + Tesseract OCR
🔍 Execute scripts by name or index


## 🚀 Quick Start

Download gameAgent.exe and make sure to install Tesseract:
https://github.com/UB-Mannheim/tesseract/wiki

## 📁 Project Structure

Create a folder in the same directory as gameAgent.exe, and you can name it after your game.
Inside this folder, create a file named commands.txt and add the screenshots of the images you want to click.

When you run gameAgent.exe, buttons with your game’s name will appear. Click the game button, and your command buttons will show up. Clicking a command button will execute that command.


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



