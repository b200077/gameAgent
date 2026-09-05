# ── addcommand_module.py ────────────────────────────────
# 從 agent_ui.py 抽出的「新增指令」相關功能
# 包含：AddCommandDialog、SaveCommandDialog、save_commands
#      以及新增指令流程會用到的截圖 OCR 功能
#      (FilenameDialog / ScreenShotWidget / open_ocr_screenshot / get_unique_filename)

import os
import re
import sys
import tempfile
import webbrowser
from datetime import datetime
from urllib.parse import quote
import cv2
import numpy as np

from PyQt5.QtWidgets import (
    QApplication, QDialog,
    QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit,
    QRadioButton, QButtonGroup,
)
from PyQt5.QtCore import Qt, QRect, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QImage, QPixmap, QColor

from PIL import Image
import pytesseract


def save_commands(name, steps, file_path):
    with open(file_path, "a", encoding="utf-8") as f:
        line = f"{name}:{{{steps}}}"
        f.write("\n" + line)

def cv2_from_pil(pil_img):
    """PIL Image 轉成 cv2 BGR numpy 陣列"""
    arr = np.array(pil_img.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def preprocess_stylized_text(img_bgr, scale=4, sat_thresh=80):
    """
    針對花俏美術字（白底黑邊、彩色裝飾背景，例如遊戲兌換碼截圖）的 OCR 前處理
    僅適合英數字場景，日文/中文翻譯截圖不要用這個
    """
    if scale != 1:
        img_bgr = cv2.resize(img_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    _, s, _ = cv2.split(hsv)
    return cv2.inRange(s, 0, sat_thresh)

def get_unique_filename(folder, base_name, ext=".png", number=0):
    suffix = "" if number == 0 else f"{number}"
    path = os.path.join(folder, f"{base_name}{suffix}{ext}")
    if not os.path.exists(path):
        return path
    return get_unique_filename(folder, base_name, ext, number + 1)


def open_ocr_screenshot(folder, callback=None):
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    window = ScreenShotWidget(folder)
    if callback:
        # signal -> callback
        window.screenshot_done.connect(callback)
    window.exec_()


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

        # 假設 self.name_input 是放置 OCR 文字的 QLineEdit / QTextEdit
        # 新增「Google搜尋(文字)」按鈕
        btn_search_text = QPushButton("Google搜尋(文字)", self)
        btn_search_text.clicked.connect(self.on_google_search_text)

        restyle_btn = QPushButton("重新辨識(兌換碼/花稍字體)")
        restyle_btn.clicked.connect(self.reocr_stylized)

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
        layout.addWidget(btn_search_text)
        layout.addWidget(restyle_btn)
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

            file_url = f"https://easypreview.unified-storage.com/read-file?file={temp_path}"

            # 🔹 Google 以圖片搜尋
            url = "https://www.google.com/searchbyimage?image_url=" + file_url

            webbrowser.open(url)

        except Exception as e:
            print("搜尋圖片失敗:", e)

    def on_google_search_text(self):
        # 取得目前文字框內的 OCR 文字
        ocr_text = self.line_edit.text()
        """將 OCR 辨識出來的文字丟給 Google 搜尋"""
        if not ocr_text or not ocr_text.strip():
            return
        # 進行 URL 編碼處理（避免中文或特殊符號斷字）
        encoded_text = quote(ocr_text.strip())
        url = f"https://www.google.com/search?q={encoded_text}"
        webbrowser.open(url)
        
    def reocr_stylized(self):
        """用顏色遮罩前處理，重新跑一次OCR，適合兌換碼這類花稍字體"""
        cv_img = cv2_from_pil(self.pil_image)
        mask = preprocess_stylized_text(cv_img)
        config = r'--psm 7 -c tessedit_char_whitelist=0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
        text = pytesseract.image_to_string(mask, lang="eng", config=config).strip()
        if text:
            self.line_edit.setText(text)
        else:
            self.line_edit.setText("辨識失敗_請手動輸入")


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

        # ---------------- 這邊開始處理圖片 -------------------------

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

        # 取得圖片指令
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
        # 清除所有radio選取
        self.group.setExclusive(False)
        self.wait_radio.setChecked(False)
        self.press_radio.setChecked(False)
        self.wait_radio2.setChecked(False)
        self.group.setExclusive(True)

    def on_mode_changed(self):
        if self.wait_radio.isChecked() and not self.line_edit.text().startswith("waitImg->"):
            self.line_edit.setText("waitImg->" + self.line_edit.text())
        elif self.press_radio.isChecked() and self.line_edit.text() == "":
            self.line_edit.setText("mouseClick")
        elif self.wait_radio2.isChecked() and self.line_edit.text() == "":
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

        dialog = SaveCommandDialog(self.commands, self.folder, self)
        # ⭐ 關鍵：等 SaveDialog 按「儲存」才關閉自己
        dialog.accepted.connect(self.on_save_accepted)
        dialog.exec_()
        self.accept()


class SaveCommandDialog(QDialog):

    def __init__(self, commands, folder, parent=None):
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
        save_commands(name, commands_text, path)
        print("指令名稱:", name)
        print("指令內容:", commands_text)
        self.accept()
