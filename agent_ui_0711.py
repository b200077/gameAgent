# ── 標準函式庫 ──────────────────────────────────────────
import os
import sys
import re
import json
import socket
import queue
import threading
import tempfile
import calendar
import time
import ctypes
from datetime import datetime, timedelta
from io import BytesIO
from tkinter import messagebox
# ── 第三方：圖形介面 ─────────────────────────────────────
import customtkinter as ctk
from customtkinter import CTkImage

from PyQt5.QtWidgets import (
    QApplication, QDialog,
    QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit,
    QRadioButton, QButtonGroup,
    QWidget, QCompleter, QCalendarWidget,
)
from PyQt5.QtCore import Qt, QRect, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QImage, QPixmap, QColor

# ── 第三方：圖像與 OCR ────────────────────────────────────
from PIL import Image, ImageGrab
import pytesseract
import pyautogui

# ── 第三方：系統與網路 ────────────────────────────────────
import pyperclip
import requests
import webbrowser

message_queue = queue.Queue()

# 確保目前目錄就是腳本位置
os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))
BASE_PATH = '.'
FILE_NAME = "schedule.json"

ctk.set_appearance_mode("dark")


def process_queue(win):
    while not message_queue.empty():
        data = message_queue.get()
        win_name = data.get("win_name")
        recieve_message = data.get("message")
        # ✅ 如果 win 名稱一致才處理
        if hasattr(win, "title") and win.title() in win_name:
            handle_ui_message(win, recieve_message)
        elif win_name == "cmd":
            print(recieve_message)

    win.after(100, process_queue, win)  # 每100ms檢查一次

def handle_ui_message(win, recieve_message):
    # 在這裡安全更新 UI 元素
    if hasattr(win, "msg_label"):
        win.msg_label.configure(text=recieve_message)


def open_ocr_screenshot(folder, callback=None):
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    window = ScreenShotWidget(folder)
    if callback:
        # signal -> callback
        window.screenshot_done.connect(callback)
    window.exec_()
    
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

def save_commands(name,steps, file_path):
    with open(file_path, "a", encoding="utf-8") as f:
        line = f"{name}:{{{steps}}}"
        f.write("\n" + line)

def command_menu(game_folder,app):
    folder_path = os.path.join(BASE_PATH, game_folder)

    win = ctk.CTkToplevel()
    win.title(game_folder)
    win.geometry("380x500")

      # 🔹 讓子視窗顯示在主視窗上層
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
    "findUnusedImg"
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

    # 讓兩欄平均分配寬度
    frame.grid_columnconfigure(0, weight=1)
    frame.grid_columnconfigure(1, weight=1)

def execute_command(command_name,  folder_path, win):
    if command_name =='inputByClipboard' :
        text = pyperclip.paste()
        pyautogui.write(text)  # 立即輸入所有文字
        return
    if command_name == 'setNameToClip':
        # 將文字寫入剪貼簿
        pyperclip.copy(win.title())
        win.msg_label.configure(text=f"{win.title()}已複製到剪貼簿")
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
        app = QApplication.instance()
        if app is None:app = QApplication(sys.argv)
        window = MainWindow()
        window.resize(400, 150)
        window.show()
        app.exec_()
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
    #傳訊息給core
    send_command_to_core(folder_path, command_name,win.title())


def send_command_to_core(folder_path, command_name, win_name):
    """透過 TCP Socket 把訊息送給 core"""

    host = "127.0.0.1"
    port = 5200  # core 的 server port

    message = {
        "folder": folder_path,
        "command": command_name,
        "win_name": win_name
    }

    try:
        data = json.dumps(message).encode("utf-8")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((host, port))
            s.sendall(data)

        print(f"✅ 已送給 core: {message}")

    except OSError as e:
        if e.winerror == 10061:
            print("⚠ Core 未啟動，嘗試以管理員身份啟動...")
            core_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "agent_core.exe")
            ctypes.windll.shell32.ShellExecuteW(None, "runas", core_path, None, None, 1)
            time.sleep(5)
            send_command_to_core(folder_path, command_name, win_name)
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


class FilenameDialog(QDialog):
    def __init__(self, pil_image, default_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle("確認檔名並儲存")
        self.resize(500, 600)

        self.result_name = None
        self.pil_image = pil_image

        # 🔹 PIL Image → QPixmap
        data = pil_image.convert("RGBA").tobytes("raw", "RGBA")
        qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimage)
        pixmap = pixmap.scaled(450, 350, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        # 🔹 圖片預覽
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setPixmap(pixmap)

        search_btn = QPushButton("Google搜尋")
        search_btn.clicked.connect(self.search_image)

        # 🔹 檔名輸入
        self.line_edit = QLineEdit(default_name)

        # 🔹 按鈕
        save_btn = QPushButton("儲存")
        cancel_btn = QPushButton("取消")
        save_btn.clicked.connect(self.accept_save)
        cancel_btn.clicked.connect(self.reject)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)

        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("檔名："))
        name_layout.addWidget(self.line_edit)

        layout = QVBoxLayout()
        layout.addWidget(self.image_label)
        layout.addWidget(search_btn)
        layout.addLayout(name_layout)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def accept_save(self):
        name = self.line_edit.text().strip()
        if name:
            self.result_name = name
            self.accept()
    def search_image(self):
        try:
            # 🔹 建立暫存圖片
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            temp_path = temp_file.name
            temp_file.close()

            # 🔹 存圖
            self.pil_image.save(temp_path, format="PNG")

            # 🔹 Google 以圖片搜尋
            url = "https://www.google.com/searchbyimage?image_url=https://easypreview.unified-storage.com/read-file?file=" + temp_path

            webbrowser.open(url)

        except Exception as e:
            print("搜尋圖片失敗:", e)
    


class ScreenShotWidget(QDialog):
    screenshot_done = pyqtSignal(str)  # 用於回傳檔名
    def __init__(self, folder):
        super().__init__()
        self.begin = None
        self.end = None
        self.folder = folder

        self.setWindowTitle("框選截圖 - 拖曳滑鼠框選要 OCR 的範圍")
        self.setWindowState(Qt.WindowFullScreen)
        self.setCursor(Qt.CrossCursor)

        # 截取靜態螢幕，凍結畫面
        screen = QApplication.primaryScreen()
        self.full_pixmap = screen.grabWindow(0)

        # 設定 QDialog 尺寸和位置跟螢幕一致
        geometry = screen.geometry()
        self.setGeometry(geometry)

    def sanitize_filename(self, name):
        name = re.sub(r'[\\/:*?"<>|]', "_", name)
        name = name.replace("\n", "").strip()
        if not name:
            return datetime.now().strftime("%Y-%m-%d %H%M%S")
        return name

    def paintEvent(self, event):
        qp = QPainter(self)

        # 1️⃣ 畫靜態螢幕
        qp.drawPixmap(0, 0, self.full_pixmap)

        if self.begin and self.end:
            rect = QRect(self.begin, self.end).normalized()

            overlay = QColor(0, 0, 0, 120)

            # 2️⃣ 畫「選取區以外」的遮罩（四塊）
            # 上
            qp.fillRect(0, 0, self.width(), rect.top(), overlay)
            # 下
            qp.fillRect(0, rect.bottom(), self.width(), self.height(), overlay)
            # 左
            qp.fillRect(0, rect.top(), rect.left(), rect.height(), overlay)
            # 右
            qp.fillRect(rect.right(), rect.top(),
                        self.width(), rect.height(), overlay)

            # 3️⃣ 紅色框線
            qp.setPen(QPen(Qt.red, 2))
            qp.drawRect(rect)

        else:
            # 尚未開始選取時，整個畫面變暗
            qp.fillRect(self.rect(), QColor(0, 0, 0, 120))

    def mousePressEvent(self, event):
        self.begin = event.pos()
        self.end = self.begin
        self.update()

    def mouseMoveEvent(self, event):
        self.end = event.pos()
        self.update()
    def qpixmap_to_pil(self, pixmap):
        image = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
        width = image.width()
        height = image.height()

        ptr = image.bits()
        ptr.setsize(image.byteCount())

        return Image.frombuffer(
            "RGBA",
            (width, height),
            bytes(ptr),
            "raw",
            "RGBA",
            0,
            1
        )

    def mouseReleaseEvent(self, event):
        self.end = event.pos()
        self.close()

        x1 = min(self.begin.x(), self.end.x())
        y1 = min(self.begin.y(), self.end.y())
        x2 = max(self.begin.x(), self.end.x())
        y2 = max(self.begin.y(), self.end.y())

        # 防呆
        if x2 - x1 < 10 or y2 - y1 < 10:
            print("截圖範圍太小，已取消")
            return

        # ✅ 從「靜態畫面」裁切
        rect = QRect(x1, y1, x2 - x1, y2 - y1)
        cropped_pixmap = self.full_pixmap.copy(rect)

        # QPixmap → PIL Image
        img = self.qpixmap_to_pil(cropped_pixmap)

        #----------------這邊開始處理圖片-------------------------

        text = pytesseract.image_to_string(img, lang='jpn+chi_tra+eng').strip()
        safe_name = self.sanitize_filename(text)

        # 🔹 直接傳 img 物件給 Dialog
        dialog = FilenameDialog(img, safe_name, self)
        if dialog.exec_() != QDialog.Accepted:
            print("使用者取消儲存")
            return

        final_name = dialog.result_name
        final_path = get_unique_filename(self.folder, final_name)
        img.save(final_path)

        #取得圖片指令
        base = os.path.basename(final_path)
        final_name_only, _ = os.path.splitext(base)
        self.screenshot_done.emit(final_name_only)

        print(f"截圖已保存：{final_path}")


class AddCommandDialog(QDialog):

    def __init__(self, folder):
        super().__init__()
        self.setWindowTitle("新增指令")
        self.resize(400, 200)

        # 輸入框
        self.line_edit = QLineEdit()
        self.line_edit.setPlaceholderText("在這裡輸入指令")

        self.commands = []   # ⭐ 儲存指令陣列
        self.folder = folder

        # 按鈕（暫時示範用）
        self.screenshot_btn = QPushButton("截圖按鈕")
        self.screenshot_btn.clicked.connect(
            lambda: open_ocr_screenshot(folder, callback=self.fill_line_edit)
        )

        # 底部控制按鈕
        self.next_btn = QPushButton("下一個指令")
        self.next_btn.clicked.connect(self.add_next_command)
        
        self.finish_btn = QPushButton("完成指令")
        self.finish_btn.clicked.connect(self.finish_command)
        

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.close)

        self.wait_radio = QRadioButton("waitImg")
        self.press_radio = QRadioButton("mouseClick")
        self.wait_radio2 = QRadioButton("wait")

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)

        self.group.addButton(self.wait_radio)
        self.group.addButton(self.press_radio)
        self.group.addButton(self.wait_radio2)

        self.wait_radio.toggled.connect(self.on_mode_changed)
        self.press_radio.toggled.connect(self.on_mode_changed)
        self.wait_radio2.toggled.connect(self.on_mode_changed)

        mode_layout = QHBoxLayout()
        mode_layout.addWidget(self.wait_radio)
        mode_layout.addWidget(self.press_radio)
        mode_layout.addWidget(self.wait_radio2)

    
        # 按鈕排版
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.next_btn)
        btn_layout.addWidget(self.finish_btn)
        btn_layout.addWidget(self.cancel_btn)

        # 主排版
        layout = QVBoxLayout()
        layout.addWidget(QLabel("新增指令"))
        layout.addWidget(self.screenshot_btn)
        layout.addLayout(mode_layout)
        layout.addWidget(self.line_edit)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def fill_line_edit(self, filename_only):
        self.line_edit.setText(filename_only)
        self.on_mode_changed()
     # ⭐ 下一個指令
    def add_next_command(self):
        text = self.line_edit.text().strip()
        if not text:
            return
        self.commands.append(text)
        self.line_edit.clear()
        #清除所有radio選取
        self.group.setExclusive(False)
        self.wait_radio.setChecked(False)
        self.press_radio.setChecked(False)
        self.wait_radio2.setChecked(False)
        self.group.setExclusive(True)
    def on_mode_changed(self):
        if self.wait_radio.isChecked() and not self.line_edit.text().startswith("waitImg->"):
            self.line_edit.setText("waitImg->" + self.line_edit.text())
        elif self.press_radio.isChecked() and self.line_edit.text() ==  "":
            self.line_edit.setText("mouseClick")
        elif self.wait_radio2.isChecked() and self.line_edit.text() ==  "":
            self.line_edit.setText("wait")

    def on_save_accepted(self):
        self.accept()   # ✅ 這時才關閉 AddCommandDialog        

    # ⭐ 完成指令
    def finish_command(self):
        # 把目前還沒按「下一個」的也收進來
        text = self.line_edit.text().strip()
        if text:
            self.commands.append(text)

        if not self.commands:
            return
        

        dialog = SaveCommandDialog(self.commands,self.folder, self)
        # ⭐ 關鍵：等 SaveDialog 按「儲存」才關閉自己
        dialog.accepted.connect(self.on_save_accepted)
        dialog.exec_()
        self.accept()
class SaveCommandDialog(QDialog):

    def __init__(self, commands,folder, parent=None):
        super().__init__(parent)
        self.setWindowTitle("儲存指令")
        self.resize(400, 300)

        self.commands = commands
        self.folder = folder

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("輸入指令名稱")

        self.commands_edit = QTextEdit()
        self.commands_edit.setPlainText(",".join(commands))

        self.save_btn = QPushButton("儲存")
        self.save_btn.clicked.connect(self.save)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.cancel_btn)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("指令名稱"))
        layout.addWidget(self.name_edit)
        layout.addWidget(QLabel("指令內容"))
        layout.addWidget(self.commands_edit)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def save(self):
        name = self.name_edit.text().strip()
        commands_text = self.commands_edit.toPlainText().strip()

        if not name or not commands_text:
            return

        # 👉 這裡之後你可以：
        # - 寫入 commands.txt
        # - 回傳給主視窗
        # - emit signal
        path = os.path.join(self.folder, "commands.txt")
        save_commands(name,commands_text,path)
        print("指令名稱:", name)
        print("指令內容:", commands_text)
        self.accept()
        
# -----------------------
# 日曆視窗
# -----------------------
class CalendarDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("選擇日期")

        layout = QVBoxLayout()
        self.calendar = QCalendarWidget()
        layout.addWidget(self.calendar)

        btn = QPushButton("確定")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)

        self.setLayout(layout)

    def get_date(self):
        date = self.calendar.selectedDate()
        return f"{date.month()}/{date.day()}"
# -----------------------
# 主視窗
# -----------------------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("簡易日曆")

        self.data = load_data()

        layout = QVBoxLayout()

        # --- 日期 ---
        date_layout = QHBoxLayout()
        self.date_edit = QLineEdit()
        self.date_btn = QPushButton("📅")

        self.date_btn.clicked.connect(self.open_calendar)

        date_layout.addWidget(QLabel("日期"))
        date_layout.addWidget(self.date_edit)
        date_layout.addWidget(self.date_btn)

        # --- 行程 ---
        task_layout = QHBoxLayout()
        self.task_edit = QLineEdit()

        # 🔥 自動完成（搜尋感）
        self.completer = QCompleter(get_all_tasks(self.data))
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.task_edit.setCompleter(self.completer)

        task_layout.addWidget(QLabel("行程"))
        task_layout.addWidget(self.task_edit)

        # --- 按鈕 ---
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("新增")
        del_btn = QPushButton("刪除")

        add_btn.clicked.connect(self.add_task)
        del_btn.clicked.connect(self.delete_task)

        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(del_btn)

        layout.addLayout(date_layout)
        layout.addLayout(task_layout)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    # -----------------------
    # 開日曆
    # -----------------------
    def open_calendar(self):
        dialog = CalendarDialog()
        if dialog.exec_():
            text = self.date_edit.text().strip()
            if not text:
                self.date_edit.setText(dialog.get_date())
            else:
                self.date_edit.setText(text + "~" +dialog.get_date())

    # -----------------------
    # 新增
    # -----------------------
    def add_task(self):
        date_str = self.date_edit.text().strip()
        task = self.task_edit.text().strip()

        if not date_str or not task:
            return

        dates = parse_dates(date_str)

        for d in dates:
            if d not in self.data:
                self.data[d] = []
            self.data[d].append(task)

        save_data(self.data)

        self.completer.model().setStringList(get_all_tasks(self.data))
        self.task_edit.clear()
    # -----------------------
    # 刪除（關鍵字）
    # -----------------------
    def delete_task(self):
        date_str = self.date_edit.text().strip()
        keyword = self.task_edit.text().strip()

        if not date_str or not keyword:
            return

        dates = parse_dates(date_str)

        for d in dates:
            if d not in self.data:
                continue

            self.data[d] = [t for t in self.data[d] if keyword not in t]

            if not self.data[d]:
                del self.data[d]

        save_data(self.data)
        self.task_edit.clear()


def get_unique_filename(folder, base_name, ext=".png", number=0):
    suffix = "" if number == 0 else f"{number}"
    path = os.path.join(folder, f"{base_name}{suffix}{ext}")
    if not os.path.exists(path): return path
    return get_unique_filename(folder, base_name, ext, number + 1)


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

                win_name = data.get("win_name")
                show_message = data.get("message")

                if not win_name or not show_message:
                    print("❌ 收到無效訊息:", data)
                    continue

                message_queue.put(data)

            except json.JSONDecodeError:
                print("❌ 收到非 JSON 訊息")
            except Exception as e:
                print(f"❌ UI 處理錯誤: {e}")

def load_data():
    if not os.path.exists(FILE_NAME):
        return {}
    with open(FILE_NAME, "r", encoding="utf-8") as f:
        return json.load(f)
    
def save_data(data):
    with open(FILE_NAME, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def get_today():
    now = datetime.now()
    return f"{now.month}/{now.day}"

def get_all_tasks(data):
    tasks = set()
    for day in data.values():
        tasks.update(day)
    return list(tasks)

def show_dates(data, date_str):
    dates = parse_dates(date_str)
    for d in dates:
        print(f"\n📅 {d}")
        # 收集精確日期 + 每月固定日的行程
        tasks = []
        if d in data:
            tasks.extend(data[d])
        # 嘗試取出當天是幾號，查 ?/day
        for wildcard_key in [k for k in data if k.startswith("*/")]:
            if resolve_wildcard(wildcard_key, d):
                tasks.extend(data[wildcard_key])
        if tasks:
            for i, task in enumerate(tasks, 1):
                print(f"{i}. {task}")
        else:
            print("（沒有行程）")

def resolve_wildcard(key, d):
    """判斷萬用日期 key 是否對應到日期 d"""
    if not key.startswith("*/"):
        return False
    day_token = key[2:]  # 取 /後面的部分
    try:
        month, day = map(int, d.split("/"))
        day_num = int(day_token)
        if day_num > 0:
            return day == day_num
        else:  # 負數，倒數
            last_day = calendar.monthrange(datetime.now().year, month)[1]
            return day == last_day + day_num + 1
    except:
        return False

# -----------------------
# 🔥 解析日期（支援多選 & 範圍）
# -----------------------
def parse_dates(input_str):
    result = []
    parts = input_str.split(",")

    for part in parts:
        token = part.strip()

        # 範圍 3/14~4/2
        if "~" in token:
            start, end = token.split("~")

            start_date = datetime.strptime(start, "%m/%d")
            end_date = datetime.strptime(end, "%m/%d")

            # 處理跨年（簡單版）
            if end_date < start_date:
                end_date = end_date.replace(year=start_date.year + 1)

            current = start_date
            while current <= end_date:
                result.append(f"{current.month}/{current.day}")
                current += timedelta(days=1)

        else:
            # 單一日期
            result.append(token)

    return result


if __name__ == "__main__":
    t = threading.Thread(target=start_socket_server, daemon=True)
    t.start()
    data = load_data()

    # 顯示今天
    today = get_today()
    show_dates(data, today)
    main_menu()

