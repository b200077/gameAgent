# ── 標準函式庫 ──────────────────────────────────────────
import os
import sys
import re
import json
import socket
import queue
import threading
import time
import ctypes
from io import BytesIO
from tkinter import messagebox

import win32gui
import win32con

# ── 第三方：圖形介面 ─────────────────────────────────────
import customtkinter as ctk
from customtkinter import CTkImage

from PyQt5.QtWidgets import (
    QApplication, QDialog,
    QVBoxLayout,
    QLabel, QLineEdit, QPushButton,
)

from tkinter import Menu

# ── 第三方：圖像與 OCR ────────────────────────────────────
from PIL import Image
import pyautogui

# ── 第三方：系統與網路 ────────────────────────────────────
import pyperclip
import requests

# ── 自訂模組：從本檔案抽出的功能 ──────────────────────────
from calendar_module import load_data, show_dates, get_today, open_calendar_window
from addcommand_module import AddCommandDialog, open_ocr_screenshot

message_queue = queue.Queue()

# 確保目前目錄就是腳本位置
os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))
BASE_PATH = '.'

ctk.set_appearance_mode("dark")


def process_queue(win):
    while not message_queue.empty():
        data = message_queue.get()
        win_name = data.get("win_name")
        recieve_message = data.get("message")
        # ✅ 如果 win 名稱一致才處理
        if hasattr(win, "title") and win.win_name in win_name:
            handle_ui_message(win, recieve_message)
        elif win_name == "cmd":
            print(recieve_message)

    win.after(100, process_queue, win)  # 每100ms檢查一次

def handle_ui_message(win, recieve_message):
    # 在這裡安全更新 UI 元素
    if hasattr(win, "msg_label"):
        win.msg_label.configure(text=recieve_message)


GWL_HWNDPARENT = -8

def find_window_by_title(title):
    """回傳標題等於 title 的最上層視窗 hwnd，找不到回傳 None"""
    result = []
    def _enum(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == title:
            result.append(hwnd)
    win32gui.EnumWindows(_enum, None)
    return result[0] if result else None
    
# 讀取 commands.txt
def load_commands(file_path):
    commands = {}
    if not os.path.exists(file_path):
        print(f"警告: 檔案不存在 -> {file_path}")
        return commands  # 檔案不存在就回傳空字典
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                name, content = line.split(":", 1)
                steps = content.strip("{}").split(",")
                commands[name.strip()] = [s.strip() for s in steps]
    return commands

def extract_images_from_step(step):
    """回傳該步驟用到的圖片檔名(不含.png)。
    判斷順序對應 agent_core.execute_one_step 的 dispatch 順序，
    把不屬於圖片比對的指令排除掉，剩下的才當圖片步驟解析。"""
    if not step or not step.strip():
        return []
    s = step.strip()
    low = s.lower()

    # 模組呼叫本身不是圖片步驟，模組內容會在 commands.txt 的對應 entry 被各自掃到
    if "->:" in s or s.startswith(":"):
        return []
    if low in ("exitcommand", "nextcommand"):
        return []
    if low.startswith("callcommand:"):
        return []
    if re.match(r'wait\d{1,2}:\d{2}', s):
        return []
    if re.match(r'waitPress->(.+)', s):
        return []
    if low == "waitclick":
        return []
    if re.match(r'"(.+)"', s):
        return []
    if re.match(r'press->(\w+)', s):
        return []
    if low in ("mouseclick", "rightclick"):
        return []
    if re.match(r'mouseMove\((\-?\d+)\_(\-?\d+)\)', s):
        return []
    if "@->" in s:
        m = re.match(r'(.+?)@->(.+)#(\d)', s)
        return [m.group(1), m.group(2)] if m else []
    if re.match(r'wait_?(\d+(\.\d+)?)', s):
        return []
    if s in ("scrollUp", "scrollDown"):
        return []
    if s.startswith(("http://", "https://")):
        return []
    if any(kw in s for kw in ("dmmgameplayer://", ".lnk", ".exe", "browndust2:")):
        return []
    if re.search(r'(\w+)-(\w+)->(.+)', s):
        m = re.match(r'(.+)-(.+)->(.+)', s)
        if not m:
            return []
        condition, value, order = m.group(1), m.group(2), m.group(3)
        if condition.startswith("!"):
            condition = condition[1:]
        images = [analysis_img_order_name(value)] if condition == "img" else []
        images.extend(extract_images_from_step(order))
        return images
    if re.match(r'minimize->(.+)', s) or re.match(r'focus->(.+)', s) or re.match(r'close->(.+)', s):
        return []

    # 排除完上面所有非圖片指令，剩下的視為圖片比對步驟
    m = re.match(r'waitImg->(.+)', s)
    if m:
        s = m.group(1)
    m = re.match(r'move->(.+)', s)
    if m:
        s = m.group(1)

    parts = [p.strip() for p in s.split("|")] if "|" in s else [s]
    return [analysis_img_order_name(p) for p in parts if p]

def find_unused_images(folder_path):
    commands = load_commands(os.path.join(folder_path, "commands.txt"))
    used = set()
    for name, steps in commands.items():
        for step in steps:
            used.update(extract_images_from_step(step))

    all_pngs = {
        os.path.splitext(f)[0]
        for f in os.listdir(folder_path)
        if f.lower().endswith(".png")
    }
    return sorted(all_pngs - used)

def analysis_img_order_name(step):
    """擷取圖片步驟中的檔名(不含副檔名)，邏輯對應 agent_core.analysis_img_order"""
    image_part = step
    if image_part.endswith(("?", "↑", "✓")):
        image_part = image_part[:-1]
    image_part = re.sub(r'[@#%][^@#%]+', '', image_part)
    return image_part

def command_menu(game_folder, app):
    folder_path = os.path.join(BASE_PATH, game_folder)

    win = ctk.CTkToplevel()
    win.title(game_folder)                 # ✅ 標題留空，避免跟遊戲視窗同名被 EnumWindows 抓到自己
    win.win_name = game_folder    # ✅ 另外記錄遊戲名稱，供其他地方取代原本 win.title() 的用途

    popup_w, popup_h = 380, 500
    game_hwnd = find_window_by_title(game_folder)

    if game_hwnd:
        left, top, right, bottom = win32gui.GetWindowRect(game_hwnd)
        x = max(left - popup_w, 0)
        y = top
        win.geometry(f"{popup_w}x{popup_h}+{x}+{y}")
    else:
        win.geometry(f"{popup_w}x{popup_h}+100+100")

    #   # 🔹 讓子視窗顯示在主視窗上層
    win.transient(app)    # 綁定主視窗
    win.lift()            # 提到最上層
    win.focus_force()     # 把焦點移到子視窗

    process_queue(win)

    # 滾動容器
    frame = ctk.CTkScrollableFrame(win, label_text=f"🎮 {game_folder}")
    frame.pack(fill="both", expand=True, padx=10, pady=(10, 60))

    commands = load_commands(os.path.join(folder_path, "commands.txt"))
    default_commands = [
    "setNameToClip",
    "editCommands",
    "ocrSavePicture",
    "addCommand",
    "openFolder",
    'addCalendar',
    "closeCore",
    "findUnusedImg",
    "bindWindow",
    "interimOrder",
    ]
    commands.update({name: [name] for name in default_commands})


    if not commands:
        msg_label = ctk.CTkLabel(win, text="⚠ 沒有可用指令")
        msg_label.pack(side="bottom", pady=10)
        return

    # 訊息顯示區
    win.msg_label = ctk.CTkLabel(win, text="")
    win.msg_label.pack(side="bottom", pady=10)

    # 設定按鈕樣式
    btn_width = 150
    btn_height = 40

    # ✅ 過濾掉 _ 開頭（隱藏用 command）
    items = [(k, v) for k, v in commands.items()
            if not k.startswith("_")]

    for idx, (key, _) in enumerate(items):
        row, col = divmod(idx, 2)

        is_default = key in default_commands  # ← 判斷是否為預設指令

        btn = ctk.CTkButton(
            frame,
            text=key,
            width=btn_width,
            height=btn_height,
            fg_color="#7b5ea7" if is_default else "#1f6aa5",       # 灰色 vs 藍色
            hover_color="#3a3a3a" if is_default else "#144d7a",    # hover 顏色
            command=lambda k=key: execute_command(k, folder_path, win)
        )
        btn.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
        btn.bind("<Button-3>", lambda e, k=key: show_step_menu(k, folder_path, win, e))

    # 讓兩欄平均分配寬度
    frame.grid_columnconfigure(0, weight=1)
    frame.grid_columnconfigure(1, weight=1)

def show_step_menu(command_name, folder_path, win, event):
    commands = load_commands(os.path.join(folder_path, "commands.txt"))
    if command_name not in commands:
        return
    steps = commands[command_name]
    if not steps:
        return

    menu = Menu(win, tearoff=0)
    for idx, step in enumerate(steps):
        menu.add_command(
            label=step,
            command=lambda i=idx: send_command_to_core(folder_path, command_name, win.win_name, start_index=i)
        )
    menu.tk_popup(event.x_root, event.y_root)
    menu.grab_release()

def execute_command(command_name,  folder_path, win):
    if command_name =='inputByClipboard' :
        text = pyperclip.paste()
        pyautogui.write(text)  # 立即輸入所有文字
        return
    if command_name == 'setNameToClip':
        # 將文字寫入剪貼簿
        pyperclip.copy(win.win_name)
        win.msg_label.configure(text=f"{win.win_name}已複製到剪貼簿")
        return
    if command_name == 'editCommands':
        os.startfile(os.path.join(folder_path, "commands.txt"))
        return
    if command_name == 'ocrSavePicture':
        open_ocr_screenshot(folder_path)
        return
    if command_name == 'addCommand':
        app = QApplication.instance()
        if app is None:app = QApplication(sys.argv)
        dialog = AddCommandDialog(folder_path)
        dialog.exec_()
        return
    if command_name == 'openFolder':
        os.startfile(folder_path)
        return
    if command_name == 'addCalendar':
        open_calendar_window()
        return
    if command_name == 'findUnusedImg':
        unused = find_unused_images(folder_path)
        if not unused:
            messagebox.showinfo("未使用的圖片", "沒有找到未使用的圖片")
            return

        confirm = messagebox.askyesno(
            "未使用的圖片",
            "找到以下未使用的圖片，是否刪除？\n\n" + "\n".join(unused)
        )
        if not confirm:
            return

        deleted, failed = [], []
        for name in unused:
            path = os.path.join(folder_path, f"{name}.png")
            try:
                os.remove(path)
                deleted.append(name)
            except OSError as e:
                failed.append(f"{name} ({e})")

        msg = f"已刪除 {len(deleted)} 張圖片"
        if failed:
            msg += "\n\n刪除失敗：\n" + "\n".join(failed)
        messagebox.showinfo("刪除結果", msg)
        return
    if command_name == 'bindWindow':
        game_hwnd = find_window_by_title(win.win_name)
        if not game_hwnd:
            win.msg_label.configure(text="⚠ 找不到遊戲視窗")
            return

        popup_hwnd = win.winfo_id()
        win32gui.SetWindowLong(popup_hwnd, GWL_HWNDPARENT, game_hwnd)
        win32gui.SetWindowPos(
            popup_hwnd, 0, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE |
            win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED
        )

        popup_w = 380
        def follow_game_window():
            if not win.winfo_exists():
                return
            if win32gui.IsWindow(game_hwnd):
                l, t, r, b = win32gui.GetWindowRect(game_hwnd)
                new_x = max(l - popup_w, 0)
                if (new_x, t) != (win.winfo_x(), win.winfo_y()):
                    win.geometry(f"+{new_x}+{t}")
                win.after(200, follow_game_window)

        win.after(200, follow_game_window)
        win.msg_label.configure(text="✅ 已綁定視窗")
        return
    if command_name == 'interimOrder':
        from PyQt5.QtWidgets import QInputDialog
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        text, ok = QInputDialog.getText(None, "臨時指令", "輸入指令(多步驟用逗號分隔)：")
        if ok and text.strip():
            send_command_to_core(folder_path, None, win.win_name, step_text=text.strip())
        return
    #傳訊息給core
    send_command_to_core(folder_path, command_name,win.win_name)


def send_command_to_core(folder_path, command_name, win_name, start_index=None, step_text=None, retry=True):
    host = "127.0.0.1"
    port = 5200
    message = {"folder": folder_path, "win_name": win_name}
    if step_text is not None:
        message["step"] = step_text
    else:
        message["command"] = command_name
    if start_index is not None:
        message["start_index"] = start_index

    try:
        data = json.dumps(message).encode("utf-8")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((host, port))
            s.sendall(data)
        print(f"✅ 已送給 core: {message}")
    except OSError as e:
        if e.winerror == 10061:
            if not retry:
                print("❌ Core 啟動後仍無法連線，放棄重試（core 可能有 bug）")
                return
            if command_name == "closeCore":
                return
            print("⚠ Core 未啟動，嘗試以管理員身份啟動...")
            core_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "agent_core.exe")
            ctypes.windll.shell32.ShellExecuteW(None, "runas", core_path, None, None, 1)
            time.sleep(5)
            send_command_to_core(folder_path, command_name, win_name, start_index, step_text, retry=False)
        else:
            print(f"❌ 無法送訊息給 core: {e}")

def main_menu():
    ctk.set_appearance_mode("dark")
    app = ctk.CTk()
    app.title("遊戲清單")
    app.geometry("480x500")

    # 滾動容器（避免遊戲太多看不到）
    frame = ctk.CTkScrollableFrame(app, label_text="📂 遊戲清單")
    frame.pack(fill="both", expand=True, padx=10, pady=10)

    # ✅ 先過濾 invisble
    folders = [f for f in os.listdir(BASE_PATH) 
               if os.path.isdir(os.path.join(BASE_PATH, f)) and not f.startswith("_") and not f.startswith(".")]

    # 設定按鈕樣式
    btn_width = 150
    btn_height = 80
    icons = load_commands("gameIconWeb.txt")  # 讀取網址字典

    for idx, folder in enumerate(folders):
        row, col = divmod(idx, 2)  # 兩列排列
        # 嘗試載入圖片
        ctk_img = None
        if folder in icons:
            url = icons[folder][0]  # 取列表中的第一個網址
            response = requests.get(url)
            pil_img = Image.open(BytesIO(response.content)).convert("RGBA")
            # 建立 CTkImage，指定大小
            ctk_img = CTkImage(light_image=pil_img, dark_image=pil_img, size=(60, 60))
        else:
            print(f"⚠ 沒有找到 {folder} 的圖標網址")
        # 建立按鈕（不放文字）
        btn = ctk.CTkButton(
            frame,
            width=btn_width,
            height=btn_height,
            text=folder,
            image=ctk_img,
            compound="top",  # 文字在上方，圖片在下方
            command=lambda f=folder: command_menu(f, app)
        )
        btn.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")

    # ✅ 強制兩欄均分
    frame.grid_columnconfigure(0, weight=1, uniform="col")
    frame.grid_columnconfigure(1, weight=1, uniform="col")

    app.mainloop()



class RequiredInputDialog(QDialog):
    def __init__(self, message, parent=None):
        super().__init__(parent)
        self.setWindowTitle("需要輸入參數")
        self.resize(300, 150)
        
        layout = QVBoxLayout()
        self.label = QLabel(message)
        layout.addWidget(self.label)
        
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("多個參數請用逗號(,)隔開")
        layout.addWidget(self.entry)
        
        self.btn = QPushButton("確認提交")
        self.btn.clicked.connect(self.accept)
        layout.addWidget(self.btn)
        self.setLayout(layout)
        
    def get_inputs(self):
        # 將使用者輸入的字串用逗號切開成陣列
        text = self.entry.text().strip()
        if not text:
            return []
        return [t.strip() for t in text.split(",")]


def start_socket_server():
    host = "127.0.0.1"
    port = 5201   # UI 接收 core 訊息的 port

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(5)

    print(f"✅ UI Socket Server 啟動中... {host}:{port}")

    while True:
        conn, addr = server.accept()
        with conn:
            try:
                data = conn.recv(64 * 1024)
                if not data:
                    continue

                message = data.decode("utf-8").strip()
                data = json.loads(message)
                process_server_data(data)
                
            except json.JSONDecodeError:
                print("❌ 收到非 JSON 訊息")
            except Exception as e:
                print(f"❌ UI 處理錯誤: {e}")

def process_server_data(data):
    win_name = data.get("win_name")
    show_message = data.get("message")

    if not win_name or not show_message:

        print("❌ 收到無效訊息:", data)
        return
    if show_message.startswith("REQ_INPUT:"):
        prompt_text = show_message.replace("REQ_INPUT:", "")
        
        # 彈出對話框 (確保在 UI 執行緒中執行)
        dialog = RequiredInputDialog(prompt_text)
        if dialog.exec_() == QDialog.Accepted:
            input_list = dialog.get_inputs()
            # 直接傳送 list 陣列過去
            send_paramaters_to_core(input_list) 
        else:
            # 如果使用者按取消，回傳空陣列免得 Core 永遠卡死
            send_paramaters_to_core([])
        return
    else:
        # 原本的其他 UI 訊息送入佇列處理
        message_queue.put(data)
        
def send_paramaters_to_core(paramaters_list):
    """透過 TCP Socket 把參數送給 core"""
    host = "127.0.0.1"
    port = 5200  # core 的 server port

    # 封裝成符合 Core 需求的 JSON 結構
    # Core 端會使用 data.get("paramaters") 來讀取這個 list
    message = {
        "paramaters": paramaters_list
    }

    try:
        data = json.dumps(message).encode("utf-8")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((host, port))
            s.sendall(data)

        print(f"✅ 已成功送給 core 參數: {message}")
    except Exception as e:
        print(f"❌ 無法連線至 Core 發送參數: {e}")
    

if __name__ == "__main__":
    t = threading.Thread(target=start_socket_server, daemon=True)
    t.start()
    data = load_data()

    # 顯示今天
    today = get_today()
    show_dates(data, today)
    main_menu()

