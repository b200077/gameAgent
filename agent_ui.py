#---------------windows------------
import os
#----------------------------------
import sys
import re
#----------------------------------
import pytesseract
#----------------------------------
from datetime import datetime
from PIL import Image,ImageGrab  # CTk 需要 PIL 處理圖片
import requests
from io import BytesIO

#------------圖形介面-------------
import customtkinter as ctk
from customtkinter import CTkImage
#---------------------------------

#-------------截圖用-----------------
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QRadioButton,
    QButtonGroup
)
from PyQt5.QtCore import Qt, QRect,pyqtSignal
from PyQt5.QtGui import QPainter, QPen,QImage, QPixmap,QColor
#----------------------------------

import pyautogui
import pyperclip

import json
import socket

import queue
import threading


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
        row, col = divmod(idx, 2)  # 兩列排列
        btn = ctk.CTkButton(
            frame,
            text=key,
            width=btn_width,
            height=btn_height,
            command=lambda k=key: execute_command(k,  folder_path, win)
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
    if command_name == 'openFolder':
        os.startfile(folder_path)
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

    except Exception as e:
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

        # 🔹 PIL Image → QPixmap
        data = pil_image.convert("RGBA").tobytes("raw", "RGBA")
        qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimage)
        pixmap = pixmap.scaled(450, 350, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        # 🔹 圖片預覽
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setPixmap(pixmap)

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

        layout = QVBoxLayout()
        layout.addWidget(self.image_label)
        layout.addWidget(QLabel("檔名："))
        layout.addWidget(self.line_edit)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def accept_save(self):
        name = self.line_edit.text().strip()
        if name:
            self.result_name = name
            self.accept()


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

        #pyperclip.copy(text)
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


if __name__ == "__main__":
    t = threading.Thread(target=start_socket_server, daemon=True)
    t.start()
    main_menu()
