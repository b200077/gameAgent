#---------------windows------------
import os
import win32pipe
import win32file
#----------------------------------
import sys
import time
import re
import keyboard
import pytesseract
import difflib
import pyautogui
import pyscreeze
from pyscreeze import ImageNotFoundException
from datetime import datetime, timedelta
import cv2
import numpy as np
import threading
import math
import pyperclip
from PIL import Image,ImageGrab  # CTk 需要 PIL 處理圖片
import requests
from io import BytesIO
import concurrent.futures

import webbrowser

#------------圖形介面-------------
import customtkinter as ctk
from customtkinter import CTkImage, CTkButton
import tkinter as tk
#---------------------------------

import ctypes

import subprocess

#-------------截圖用-----------------
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import QPainter, QPen
#----------------------------------


import mouse


# 確保目前目錄就是腳本位置
os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))

BASE_PATH = '.'
WEEK_MAP= ["星期一","星期二","星期三","星期四","星期五","星期六","星期日"]
WEEK_MAP_ORDER= ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]


ctk.set_appearance_mode("dark")

STOP_EVENT = threading.Event()
NEXT_EVENT = threading.Event()
PAUSE_EVENT = threading.Event()

def esc_pressed():
    STOP_EVENT.set()
    NEXT_EVENT.set()
    print("⛔ 偵測到 ESC,終止所有指令")

keyboard.add_hotkey('esc', esc_pressed, suppress=False)

def tab_pressed():
    NEXT_EVENT.set()
    print("⛔ 偵測到 TAB,執行下一個指令")

keyboard.add_hotkey('tab', tab_pressed, suppress=False)

def space_pressed():
    if not PAUSE_EVENT.is_set():
        PAUSE_EVENT.set()
        NEXT_EVENT.set()
        print("⛔ 偵測到 space,暫停目前指令")

keyboard.add_hotkey('space', space_pressed, suppress=False)



# 讀取 commands.txt
def load_commands(file_path):
    commands = {}
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

def save_commands(commands, file_path):
    with open(file_path, "w", encoding="utf-8") as f:
        for name, steps in commands.items():
            line = f"{name}:{{{', '.join(steps)}}}"
            f.write(line + "\n")
# 展開模組
def expand_steps(steps, commands,condition=""):
    expanded = []
    mulExpanded = []
    #先展開*號
    for step in steps:
        match = re.match(r'(.+)\*(\d+)$', step)
        if match:
            order, count = match.groups()
            for _ in range(int(count)):
                mulExpanded.append(order.strip())
        else:
            mulExpanded.append(step)
    #再展開模組
    for step in mulExpanded:
        if "->:" in step or step.startswith(":"):
            stepCondition,module_name = step.split(":", 1)
            new_condition = condition if condition else stepCondition
            if module_name in commands:
                expanded.extend(expand_steps(commands[module_name], commands,new_condition))
            else:
                print(f"⚠ 找不到模組 {module_name}")
        else:
            expanded.append(condition + step)
    return expanded

def analysis_img_order(step):
    backup_plan = "Next"
    required_text = False
    image_part = step
    target_index = 1   # 預設第 1 個

    if "?" in image_part:
        backup_plan = "ignore"
        image_part = image_part.replace("?", "")
    if "↑" in image_part:
        backup_plan = "Previous"
        image_part = image_part.replace("↑", "")

    match = re.match(r'(.+?)@(.+)', image_part)
    if match:
        image_part = match.group(1)
        required_text = match.group(2)

    match = re.match(r'(.+?)#(\d+)', image_part)
    if match:
        image_part = match.group(1)
        target_index = int(match.group(2))

    return backup_plan, image_part, target_index, required_text

def update_message(win, msg_label, text):
    """
    統一更新訊息
    win       : CTkToplevel 或 CTk 主視窗
    msg_label : 顯示訊息的 CTkLabel
    text      : 要顯示的文字
    """
    msg_label.configure(text=text)
    win.update()  # 立刻刷新 UI，確保訊息立即顯示


def filter_overlapping_boxes(boxes, min_distance=20):
    """
    過濾掉重複或重疊的偵測框
    :param boxes: locateAllOnScreen 回傳的 list
    :param min_distance: 中心點距離小於這個值，就視為重複
    """
    filtered = []
    for box in boxes:
        cx, cy = box.left + box.width // 2, box.top + box.height // 2
        too_close = False
        for fb in filtered:
            fcx, fcy = fb.left + fb.width // 2, fb.top + fb.height // 2
            dist = math.hypot(cx - fcx, cy - fcy)
            if dist < min_distance:
                too_close = True
                break
        if not too_close:
            filtered.append(box)
    return filtered


def find_target_img(full_path, target_index, required_text,thread_event,on_done=None):
    img = cv2.imdecode(np.fromfile(full_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    try:
        locations = list(pyautogui.locateAllOnScreen(img, confidence=0.8))
    except :
        locations = []
    if not locations:
        #print(f"⚠ 找不到圖片 {full_path} ")
        if on_done : on_done(None)
        return
    if target_index > len(locations):
        print(f"⚠ 找到 {len(locations)} 個，但沒有第 {target_index} 個")
        if on_done : on_done(None)
        return
    # 不需要文字匹配，直接取目標
    if not required_text:
        loc = locations[target_index - 1]
        if on_done : on_done(pyautogui.center(loc))
        return 
    pending = len(locations)
    lock = threading.Lock()
    # ---- 並行 OCR 模式 ----
    def ocr_task(loc):
        nonlocal pending
        # 🔹 加這裡：偵測 NEXT_EVENT 是否已觸發
        if thread_event.is_set(): return
        region = (int(loc.left), int(loc.top), int(loc.width), int(loc.height))
        screenshot = pyautogui.screenshot(region=region)
        # 把 OCR 結果轉成文字
        try:
            text = pytesseract.image_to_string(screenshot, lang="chi_tra+eng+jpn").strip()
        except RuntimeError:
            print("⚠️ OCR逾時", flush=True)
            return
        text = re.sub(r'\s+', '', text)
        print(f"📄 OCR辨識結果: {text}", flush=True)
        with lock:
            if thread_event.is_set():
                return
            if required_text in text:
                print("✅ OCR 匹配成功")
                if on_done: on_done(pyautogui.center(loc))
                return
            pending -= 1
            if pending == 0:
                print("❌ 所有 OCR 完成，沒有匹配")
                if on_done: on_done(None)

    for loc in locations:
        t = threading.Thread(target=ocr_task, args=(loc,), daemon=True)
        t.start()
  

# 執行模組/指令
def execute_command(command_name, commands, folder_path, win, msg_label):
    update_message(win, msg_label, f"開始執行 '{command_name}'")
    if command_name not in commands:
        update_message(win, msg_label, f"❌ 找不到指令 {command_name}")
        return

    STOP_EVENT.clear()
    PAUSE_EVENT.clear()
    steps = expand_steps(commands[command_name], commands)
    match = re.match(r'>check_record_(\w)(\d+)', steps[0])
    if match:
        record_path = os.path.join(folder_path, "commandRecord.txt")
        command_record = load_commands(record_path)
        time_str = command_record[command_name][0]
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        # 比較相差天數
        delta = now - dt
        time_unit = match.group(1)
        unit_number  = match.group(2)
        if time_unit == "d" :
            if delta.days > unit_number :
                command_record[command_name][0] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                save_commands(command_record, record_path)
            else:
                print(f"相差天數小於{delta.days}，不執行指令")
                return
    
    def check(index,backup_plan):
        NEXT_EVENT.clear()
        if index >= len(steps):
            update_message(win, msg_label, f"{command_name}指令已完成")
            return

        if STOP_EVENT.is_set():
            update_message(win, msg_label, f"⛔ 偵測到 ESC, {command_name}指令中斷")
            return

        if PAUSE_EVENT.is_set() or backup_plan == "Pause":
            update_message(win, msg_label, f"{steps[index]} 步驟暫停")
            pause_script(win,lambda : check(max(index-1, 0),"Next"))
            # 等待使用者解除暫停後再呼叫 check
            return
        if backup_plan == "Previous":
            index -= 2
        # 執行當前步驟，完成後自動呼叫下一步
        execute_one_step(
            steps[index],
            folder_path,
            win,
            msg_label,
            on_done=lambda backup_plan="Next": check(index + 1, backup_plan)
        )

    # 從第一步開始
    check(0,"Next")

# 等待到某個時間點
def wait_until_time(target_time):
    while True:
        now = datetime.now()
        remaining = (target_time - now).total_seconds()

        if remaining <= 0:
            return True

        if remaining > 60:
            # 還有超過 1 分鐘 → 每 1 秒檢查一次
            time.sleep(1)
        else:
            # 最後 1 分鐘 → 提高精度，每 0.2 秒檢查一次
            time.sleep(0.2)
       
    

# 等待幾秒
def wait_seconds(win, msg_label, seconds,on_done=None):
    """
    非阻塞等待指定秒數。
    - win: customtkinter 主視窗
    - seconds: 要等待的秒數
    - on_done: (可選) 等待完成後要執行的回呼函式
    """
    remaining = seconds  # 每次都建立新的獨立變數
    def check():
        nonlocal remaining  # 宣告使用外層變數
        if NEXT_EVENT.is_set():
            msg_label.configure(text="⏹ 等待已中止")
            if on_done : on_done("Next")
            print("⏹ NEXT_EVENT 被觸發，中止等待")
            return

        if remaining <= 0:
            msg_label.configure(text=f"✅ 已等待 {remaining:.1f} 秒")
            print(f"✅ 已等待 {seconds:.1f} 秒")
            if on_done : on_done("Next")
            return

        # 更新 label
        msg_label.configure(text=f"⏱ 還剩 {remaining:.1f} 秒...")
        remaining = round(max(0, remaining - 0.1), 1)  # 每次減 0.1 秒
        win.after(100, check)

    win.after(0, check)

def wait_button(win, button,on_done=None):
    """
    等待某個按鍵被按下，或 NEXT_EVENT 被觸發。
    - win: 視窗物件 (CTk 或 CTkToplevel)
    - button: 要監聽的按鍵名稱 (例如 "space")
    - callback: 當按鍵或 NEXT_EVENT 觸發時呼叫的函式
    """
    if NEXT_EVENT.is_set() or keyboard.is_pressed(button):
        if on_done : on_done()
        return
    else:
        win.after(100, lambda: wait_button(win, button,on_done))  # 每 100ms 檢查一次

def wait_mouse(win, button,on_done=None):
    if NEXT_EVENT.is_set() or mouse.is_pressed(button):
        if on_done : on_done()
        return
    else:
        win.after(100, lambda: wait_mouse(win, button,on_done))  # 每 100ms 檢查一次
        
def execute_one_step(step,folder_path,win, msg_label,on_done=None):
    print(step)
    def image_click(center,backup_plan,no_click=False):
        if center != False and not no_click :
            #避免過快點擊出現的按鈕
            pyautogui.moveTo(center)
            pyautogui.click()
        if on_done : on_done(backup_plan)
    # 判斷是否定時執行
    # 假設 step 是像 "wait_14:30" 或 "wait_02:05" 這樣的字串
    # 在 excuse_one_step 裡替換
    #---------------搶票用--------------
    if re.match(r'wait_?\d{1,2}:\d{2}', step):
        target_time_str = re.findall(r'wait_?(\d{1,2}:\d{2})', step)[0]
        now = datetime.now()
        target_time = datetime.strptime(target_time_str, "%H:%M").replace(
            year=now.year, month=now.month, day=now.day
        )
        if target_time < now:
            target_time += timedelta(days=1)

        print(f"⏱ 等待至 {target_time.strftime('%Y-%m-%d %H:%M:%S')} (搶票模式)")
        wait_until_time(target_time)
        print("🚀 時間到，開始執行！")
        return
    if re.match(r'waitPress->(.+)', step):
        button = re.match(r'waitPress->(.+)', step).group(1)
        print(f"⏱ 等待 {button} 按鍵")
        wait_button(win,button,on_done)
        return
    if re.match(r'waitMouse->(.+)', step):
        button = re.match(r'waitMouse->(.+)', step).group(1)
        print(f"⏱ 等待滑鼠 {button} 按鍵")
        wait_mouse(win,button,on_done)
        return
    # 判斷有無文字輸入需求
    if re.match(r'"(.+)"', step):
        text = re.match(r'"(.+)"', step).group(1)
        # 英文鍵盤（美式） 
        ctypes.windll.user32.LoadKeyboardLayoutW("00000409", 1)
        pyautogui.write(text)  # 立即輸入所有文字
        if on_done: on_done()
        return
        # 判斷有無按鈕需求
    if re.match(r'press->(\w+)', step):
        text = re.match(r'press->(\w+)', step).group(1)
        pyautogui.press(text)   # 單次按下
        if on_done: on_done()
        return
    if step == 'mouseClick':
        # 按一下滑鼠左鍵
        pyautogui.click()
        if on_done: on_done()
        return
    match = re.match(r'mouseMove\((\-?\d+)\_(\-?\d+)\)', step)
    if match:
        x, y = map(int, match.groups())  # 將字串轉成整數
        pyautogui.moveRel(x, y)          # 相對移動
        if on_done: on_done()
        return
    if "@->" in  step:
        enter_captcha(step, folder_path,on_done)
        return
    #-------------------------------------
    if re.match(r'wait_?(\d+(\.\d+)?)', step):
        seconds = float(re.findall(r'wait_?(\d+(\.\d+)?)', step)[0][0])
        update_message(win, msg_label, f"⏱ 等待 {seconds} 秒")
        wait_seconds(win, msg_label,seconds,on_done)
        return
    if step in ("scrollUp", "scrollDown"):
        pyautogui.scroll(500 if step == "scrollUp" else -500)
        if on_done:on_done()
        return
    if step.startswith(("http://", "https://")):
        launch_webdriver(step,win, msg_label)
        if on_done:on_done()
        return
    if step.startswith("dmmgameplayer://") or ".lnk" in step:
        launch_app(step)
        if on_done:on_done()
        return
    # 判斷其他條件    
    if re.match(r'(.+)-(.+)->(.+)', step):            
        check_condition(step,folder_path,win, msg_label)
        if on_done:on_done()
        return
    if step =='inputByClipboard' :
        text = pyperclip.paste()
        pyautogui.write(text)  # 立即輸入所有文字
        if on_done:on_done()
        return
    if step == 'setNameToClip':
        # 將文字寫入剪貼簿
        pyperclip.copy(win.title())
        if on_done:on_done()
        return
    if step == 'editCommands':
        # 將文字寫入剪貼簿
        os.startfile(os.path.join(folder_path, "commands.txt"))
        if on_done:on_done()
        return
    if step == 'ocrSavePicture':
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        window = ScreenShotWidget()
        window.show()
        app.exec_()
        return
    # 判斷or條件 
    if "|" in step:
        steps = [s.strip() for s in step.split("|") if s.strip()]
    else:
        steps = [step]

    thread_event = threading.Event()
    for s in steps:
        t = threading.Thread(
            target=wait_until_image,
            args=(win, s, folder_path, thread_event, image_click),
            daemon=True
        )
        t.start()


def pause_script(win,on_done):
    PAUSE_EVENT.clear()
    wait_button(win,"space",on_done)
    
            
def check_condition(step,folder_path,win, msg_label):
    def condition_noimage(center):
        if center is None : 
            update_message(win, msg_label,f"沒有找到圖片{image_part}.png,不執行指令{order}")
            return False
        NEXT_EVENT.clear()
        execute_one_step(order,folder_path,win, msg_label)
    
    condition = None
    order = None
    conditionValue = None
    # 先拆 -> 判斷條件
    match = re.match(r'(.+)-(.+)->(.+)',step)
    if not match: return False
    condition = match.group(1)
    conditionValue = match.group(2)
    order = match.group(3)
    #week-Sun->free
    if condition == "week"  :
        day = datetime.now().strftime("%a")
        if day in WEEK_MAP_ORDER:
            index = WEEK_MAP_ORDER.index(conditionValue)
            if conditionValue != day : 
                update_message(win, msg_label,f"今天不是{WEEK_MAP[index]},不執行指令{order}")
                return False
            execute_one_step(order,folder_path,win, msg_label)
        else:
            update_message(win, msg_label,"星期縮寫有誤，請輸入Mon,Tue,Wed,Thu,Fri,Sat,Sun")
    elif condition == "img"  :
        _, image_part, target_index, required_text = analysis_img_order(conditionValue)
        full_path = os.path.join(folder_path, f"{image_part}.png")
        find_target_img(full_path, target_index, required_text,win,condition_noimage)            
    else:
        return False

def enter_captcha(step, folder_path,on_done):
    # 先拆 @-> 判斷文字需求
    match = re.match(r'(.+?)@->(.+)#(\d)', step)
    if not match:
        print(f"❌ 格式錯誤: {step}")
        return False

    input_box_path = os.path.join(folder_path, f"{match.group(1)}.png")
    captcha_image_path = os.path.join(folder_path, f"{match.group(2)}.png")  
    count = match.group(3)
    img = cv2.imdecode(np.fromfile(captcha_image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    # 找 captcha 圖片並辨識
    try:
        captcha_matches = list(pyautogui.locateAllOnScreen(img, confidence=0.6))
    except Exception:
        captcha_matches = []
    if not captcha_matches:
        print(f"❌ 找不到圖片 {match.group(2)}.png")
        return False
    #---------------tesseract------------------
    for loc in captcha_matches :
        region = (int(loc.left), int(loc.top), int(loc.width), int(loc.height))
        screenshot = pyautogui.screenshot(region=region)
        screenshot = np.array(screenshot)
        gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2, fy=2)  # 放大兩倍
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # 只允許 a-z
        custom_config = r'--psm 6 -c tessedit_char_whitelist=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'

        text = pytesseract.image_to_string(thresh, lang="eng", config=custom_config).strip()
        text = re.sub(r'\s+', '', text)
        print(f"📄 OCR辨識結果: {text}")
        # 用#來判斷要輸入幾碼
        if len(text) == count :
            break
    #------------------ddddocr------------------
    # for loc in captcha_matches:
    #     # 擷取圖片區域
    #     region = (int(loc.left), int(loc.top), int(loc.width), int(loc.height))
    #     screenshot = pyautogui.screenshot(region=region)

    #     # 轉成 bytes 給 ddddocr
    #     img_bytes = screenshot.tobytes()

    #     # 如果 ddddocr 無法讀 t​obytes，可改此方式：
    #     # img_bytes = np.array(screenshot)
    #     # img_bytes = cv2.imencode('.png', img_bytes)[1].tobytes()

    #     # OCR 辨識
    #     text = ddocr.classification(img_bytes)
    #     text = text.strip()
    #     text = re.sub(r'\s+', '', text)

    #     print(f"📄 OCR辨識結果: {text}")

    #     # 用 # 判斷是否達到指定長度
    #     if len(text) == count:
    #         break
    #------------------------------------
    # 找輸入框圖片並輸入
    img = cv2.imdecode(np.fromfile(input_box_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    try:
        input_matches = list(pyautogui.locateAllOnScreen(img, confidence=0.8))
    except Exception:
        input_matches = []
    if not input_matches:
        print(f"❌ 找不到圖片 {match.group(1)}.png")
        return False

    loc = input_matches[0] 
    center = pyautogui.center(loc)

    # 先移動滑鼠，再點擊
    pyautogui.moveTo(center)
    pyautogui.click()
    pyautogui.write(text)  # 立即輸入所有文字
    if on_done: on_done()

def wait_until_image(win,step, folder_path,thread_event,on_done=None):
    """非阻塞等待圖片，找到後呼叫 on_done(result)"""
    if win is None:
        raise ValueError("請提供 customtkinter 主視窗 win")
    timeout=15
    no_click=False
    no_move=False
    backup_plan, image_part, target_index, required_text = analysis_img_order(step)
    match = re.match(r'waitImg->(.+)', step)
    if match:
        timeout=0
        no_click=True
        step = match.group(1)

    wait_forever = (timeout == 0)
    if backup_plan == "ignore": timeout = 0.4
    if backup_plan == "Previous": timeout = 0.1

    full_path = os.path.join(folder_path, f"{image_part}.png")
    # ✅ 檢查檔案是否存在
    if not os.path.exists(full_path):
        print(f"❌ 找不到檔案: {full_path}")
        if on_done :on_done(False,"Pause")
        return 

    print(f"🔍 等待圖片：{image_part}.png (目標第 {target_index} 個)")
    start = time.time()
    def find_image(center):
                if NEXT_EVENT.is_set() and not thread_event.is_set():
                    if on_done : on_done(False,backup_plan)
                    return
                if center is not None:
                    print(f"✅ 找到 {image_part}.png 第 {target_index} 個 (文字匹配: {required_text})")
                    if on_done and not thread_event.is_set()  :
                        thread_event.set()
                        on_done(center,"Next",no_click)
                    return
                # 超時判斷
                if time.time() - start >= timeout and not wait_forever:
                    print(f"⏳ 等待 {image_part}.png 超時 {timeout} 秒")
                    if backup_plan == "Next": PAUSE_EVENT.set()
                    if  on_done and not thread_event.is_set() : on_done(False,backup_plan)    
                    return 
                win.after(
                                100,
                                lambda: find_target_img(
                                    full_path, target_index, required_text, thread_event, find_image
                                )
                            )
    find_target_img(full_path, target_index, required_text,thread_event,find_image)




def command_menu(game_folder,app):
    folder_path = os.path.join(BASE_PATH, game_folder)

    win = ctk.CTkToplevel()
    win.title(game_folder)
    win.geometry("380x500")

      # 🔹 讓子視窗顯示在主視窗上層
    win.transient(app)    # 綁定主視窗
    win.lift()            # 提到最上層
    win.focus_force()     # 把焦點移到子視窗

    # 滾動容器
    frame = ctk.CTkScrollableFrame(win, label_text=f"🎮 {game_folder}")
    frame.pack(fill="both", expand=True, padx=10, pady=(10, 60))

    commands = load_commands(os.path.join(folder_path, "commands.txt"))
    commands["setNameToClip"] = ["setNameToClip"]
    commands["editCommands"] = ["editCommands"]
    

    if not commands:
        msg_label = ctk.CTkLabel(win, text="⚠ 沒有可用指令")
        msg_label.pack(side="bottom", pady=10)
        return

    # 訊息顯示區
    msg_label = ctk.CTkLabel(win, text="")
    msg_label.pack(side="bottom", pady=10)

    # 設定按鈕樣式
    btn_width = 150
    btn_height = 40

    for idx, (key, _) in enumerate(commands.items()):
        if key.startswith("_") :
            continue
        row, col = divmod(idx, 2)  # 兩列排列
        btn = ctk.CTkButton(
            frame,
            text=key,
            width=btn_width,
            height=btn_height,
            command=lambda k=key: execute_command(k, commands, folder_path, win, msg_label)
        )
        btn.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
    

    # 讓兩欄平均分配寬度
    frame.grid_columnconfigure(0, weight=1)
    frame.grid_columnconfigure(1, weight=1)

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
def launch_webdriver(url,win, msg_label):
    # 打開一個網頁
    update_message(win, msg_label," 開啟網頁 " + url)
    # 開啟指定網址（使用預設瀏覽器）
    webbrowser.open_new_tab(url)   
def launch_app(url):
    subprocess.run(["start", url], shell=True)


def start_pipe_server():
    # 定義命名管道名稱
    pipe_name = r'\\.\pipe\script_recieve_server'
    while True:
        try:
            # 创建命名管道
            pipe_server = win32pipe.CreateNamedPipe(
                pipe_name,
                win32pipe.PIPE_ACCESS_DUPLEX,  # 访问模式
                win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,  # 管道模式
                win32pipe.PIPE_UNLIMITED_INSTANCES,  # 最大实例数
                1024,  # 输出缓冲区大小
                1024,  # 输入缓冲区大小
                0,  # 默认超时
                None  # 安全属性
            )

            print("等待客戶端連接...")
            win32pipe.ConnectNamedPipe(pipe_server, None)  # 等待客户端连接
            print("客戶端已連接.")

            # 读取客户端发送的消息
            hr, message = win32file.ReadFile(pipe_server, 64 * 1024)
            if hr == 0:
                decoded_message = message.decode().strip()  # 解码并去掉多余的空格 
                print(f"decoded_message: {decoded_message}") 
                # if decoded_message == "refreshOpenSample":
                #     messages = []
                #     pipes = list_named_pipes("easyPreview")
                #     for pipe in pipes:
                #         app.logger.info(f"pipe: {pipe}")                         
                #         messages.append(pipe)
                # if decoded_message not in messages:
                #     messages.append(decoded_message)
                # order = decoded_message.split(' ')
                # app.logger.info(f"order: {order}") 
                # if order[1] not in messages and order[0] == "add":
                #     messages.append(order[1])
                # if order[1] in messages and order[0] == "remove":
                #     messages.remove(order[1])
                # app.logger.info(f"可用實例: {messages}") 
                #with lock:  # 使用锁来保护对 messages 的访问
                    
            win32file.CloseHandle(pipe_server)  # 确保关闭管道
        except Exception as ex:
            print(f"錯誤: {ex}")

class ScreenShotWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.begin = None
        self.end = None

        self.setWindowTitle("框選截圖 - 拖曳滑鼠框選要OCR的範圍")
        self.setWindowState(Qt.WindowFullScreen)
        self.setWindowOpacity(0.3)  # 半透明
    def sanitize_filename(self,name):
        # 移除 Windows 不允許的字元
        name = re.sub(r'[\\/:*?"<>|]', "_", name)
        # 移除換行與前後空白
        name = name.replace("\n", "").strip()
        # 避免空字串
        return name if name else "output"

    def paintEvent(self, event):
        if self.begin and self.end:
            qp = QPainter(self)
            pen = QPen(Qt.red, 2, Qt.SolidLine)
            qp.setPen(pen)
            rect = QRect(self.begin, self.end)
            qp.drawRect(rect)

    def mousePressEvent(self, event):
        self.begin = event.pos()
        self.end = self.begin
        self.update()

    def mouseMoveEvent(self, event):
        self.end = event.pos()
        self.update()

    def mouseReleaseEvent(self, event):
        self.end = event.pos()
        self.close()

        x1 = min(self.begin.x(), self.end.x())
        y1 = min(self.begin.y(), self.end.y())
        x2 = max(self.begin.x(), self.end.x())
        y2 = max(self.begin.y(), self.end.y())

        img = ImageGrab.grab(bbox=(x1, y1, x2, y2))
        #name = datetime.now().strftime("%Y-%m-%d %H:%M:%S") 
        text = pytesseract.image_to_string(img, lang='jpn+chi_tra+eng')

        print("\n=== OCR 內容 ===")
        print(text)
        pyperclip.copy(text)
        safe_text = self.sanitize_filename(text)
        img.save(os.path.join(BASE_PATH,"截圖辨識", f"{safe_text}.png"))
           
        print(f"截圖已保存：{safe_text}.png")
    
if __name__ == "__main__":
    threading.Thread(target=start_pipe_server, daemon=True).start()
    main_menu()
