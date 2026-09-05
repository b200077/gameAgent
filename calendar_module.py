# ── calendar_module.py ──────────────────────────────────
# 從 agent_ui.py 抽出的「日期 / 行事曆」相關功能
# 包含：資料存取(load_data/save_data)、日期解析(parse_dates/resolve_wildcard)、
#      主視窗(MainWindow)、日期選擇對話框(CalendarDialog)

import sys
import os
import json
import calendar
from datetime import datetime, timedelta

from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton,
    QWidget, QCompleter, QCalendarWidget,
)
from PyQt5.QtCore import Qt

FILE_NAME = "schedule.json"

WEEK_MAP = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
WEEK_MAP_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# -----------------------
# 資料存取
# -----------------------
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
    except Exception:
        return False


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
                self.date_edit.setText(text + "~" + dialog.get_date())

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


# -----------------------
# 開啟日曆視窗（GUI 按鈕 / CLI 共用，避免各自重寫 QApplication 樣板）
# -----------------------
def open_calendar_window():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(400, 150)
    window.show()
    app.exec_()


# -----------------------
# 命令列主程式：可直接 `python calendar_module.py` 執行
# -----------------------
def main():
    today = get_today()
    print(f"📅 今天 ({today})")
    show_dates(load_data(), today)

    while True:
        cmd = input("\n指令 (edit / show [日期] / exit)：").strip()

        if cmd == "edit":
            open_calendar_window()  # 存檔都在視窗裡完成，結束後直接重新讀檔即可
        elif cmd.startswith("show"):
            _, *rest = cmd.split()
            date_str = rest[0] if rest else today
            show_dates(load_data(), date_str)
        elif cmd == "exit":
            break


if __name__ == "__main__":
    main()
