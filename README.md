GameAgent v2 – Image-Based Automation System

GameAgent is a powerful, image-based automation system for PC games, emulators, and mobile games running on desktop environments. It allows you to automate daily sign-ins, reward collection, repetitive tasks, and complex workflows — all without modifying game files or memory.

GameAgent is designed for non-programmers: simply prepare reference images and write simple commands in a text file, and GameAgent handles the rest.

Core Concept

GameAgent uses image recognition instead of fixed screen coordinates, making automation scripts robust and modular. To create automation scripts:

Create a folder for each game.
Add reference images (buttons, icons, UI elements).
Write simple command instructions in a commands.txt script.

This design significantly reduces duplicated work when creating or maintaining scripts.

Key Advantages
1️⃣ Image-Based Clicking (No Fixed Window Position)
Actions are performed by matching images, not absolute coordinates.
No need to lock the game window in an exact position.
Scripts remain stable as long as the window’s aspect ratio matches the screenshots.
2️⃣ OCR Verification for Accurate Actions
Optional OCR text recognition ensures the correct button is clicked.
Useful when the same UI element appears in multiple contexts (e.g., multiple stages with identical backgrounds).
Example: click an image only if the detected text contains “Lv.7”.
3️⃣ Multi-Image Detection Logic
Supports simultaneous detection of multiple images.
Configure actions such as “click when any of these images appear”.
Ideal for branching UI states, popups, or random events.
Features

✨ Image-based automation (no memory hacking)
📜 Simple script commands (commands.txt)
🧩 Modular structure (one folder per game)
🔄 OCR support (text & captcha recognition)
⏸️ Pause and resume execution
🧵 Parallel execution support
⚙️ Built with PyAutoGUI + Tesseract OCR
🔍 Execute scripts by name or index

Quick Start
Download gameAgent.exe and install Tesseract OCR
.
Create a folder named after your game in the same directory as gameAgent.exe.
Add commands.txt and reference .png images of the UI elements you want to automate.
Run gameAgent.exe, click your game’s button, and execute the command buttons.
Project Structure
game_folder/
├─ commands.txt    # automation script
├─ *.png           # screenshots of UI elements
Command Script Syntax
Flow Control
Symbol	Description
↑	Shorten image wait time, retry previous step if not detected
?	Shorten image wait time, skip to next step if not detected
*-*->*	Conditional execution
Wait / Detection
Command	Description
waitImg	Wait until an image appears
waitPress	Wait for keyboard input
waitMouse	Wait for mouse input
wait1	Wait 1 second (supports decimal)
Input / Actions
Command	Description
press	Press a keyboard key
mouseClick	Left mouse click
mouseMove(x_y)	Move mouse to coordinates
scrollUp / scrollDown	Mouse wheel scroll
Special
Command	Description
"text"	Type alphanumeric text
@	OCR captcha input
#	Specify index if multiple pictures appear on screen
http://	Open URL
.lnk	Execute shortcut via cmd

Example:

daily:{quest,wait1,subQuest,wait1,evolveQuest,wait1,evolve2@II,confirm,wait1,auto,wait1,skip#2,max,wait1,ok,toQuest}
v2 Updates
5200 Port Socket API for remote script control
Core and UI are separated, improving stability
Fixed image wait and execution issues from v1
Legacy scripts are stored in /legacy/v1
No Programming Required

Even without coding skills, you can create powerful automation:

Take screenshots of buttons or UI elements
Write image names + simple symbols in commands.txt
GameAgent executes near-program-level automation workflows

Supported Automation Features:

🖼️ Wait for images to appear before executing
🖱️ Wait for human mouse input (human-machine seamless control)
🔄 Automatic workflow logic (not just blind clicking)
OCR-based button recognition to avoid clicking the wrong UI

Safety Features:

⛔ Press ESC anytime to force stop
⏸️ Spacebar to pause/resume
No “uncontrollable loops” like some other automation tools

Highlights:

More flexible than traditional script tools (no programming required)
More reliable than AI agents (no misjudgment)

Use Cases:

Automating mobile game tasks
Repetitive PC operations
Click-based workflows
Socket API – Remote Control Example

GameAgent opens a local server on:

127.0.0.1:5201

You can send JSON messages via TCP to control the UI:

import socket
import json

data = {
    "win_name": "Emulator1",
    "message": "start_script"
}

client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect(("127.0.0.1", 5201))
client.sendall(json.dumps(data).encode("utf-8"))
client.close()
Disclaimer

This project is for educational and personal use only. Use at your own risk. The author is not responsible for account bans.

License

Apache License 2.0