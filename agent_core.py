#---------------windows------------
import os
import win32gui
import win32con
#----------------------------------
import sys
import time
import re
import keyboard
#----------------------------------
import pytesseract
#----------------------------------
import pyautogui
from datetime import datetime, timedelta
import cv2
import numpy as np
import threading
import pyperclip
import webbrowser

import ctypes

import subprocess

#----------------------------------


import mouse
import uuid

from dataclasses import dataclass

import json
import socket


# 確保目前目錄就是腳本位置
os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))


BASE_PATH = '.'
WEEK_MAP= ["星期一","星期二","星期三","星期四","星期五","星期六","星期日"]
WEEK_MAP_ORDER= ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]



STOP_EVENT = threading.Event()
NEXT_EVENT = threading.Event()
PAUSE_EVENT = threading.Event()

WAIT_TOKEN = None  # 全域或放在 controller 裡

def esc_pressed():
    STOP_EVENT.set()
    NEXT_EVENT.set()
    update_message("⛔ 偵測到 ESC,終止所有指令")

keyboard.add_hotkey('esc', esc_pressed, suppress=False)

def tab_pressed():
    NEXT_EVENT.set()
    update_message("⛔ 偵測到 TAB,執行下一個指令")

keyboard.add_hotkey('tab', tab_pressed, suppress=False)

def space_pressed():
    if not PAUSE_EVENT.is_set():
        PAUSE_EVENT.set()
        NEXT_EVENT.set()
        update_message("⛔ 偵測到 space,暫停目前指令")

keyboard.add_hotkey('space', space_pressed, suppress=False)

# 讀取 commands.txt
def load_commands(file_path):
    commands = {}
    if not os.path.exists(file_path):
        update_message(f"警告: 檔案不存在 -> {file_path}")
        return commands  # 檔案不存在就回傳空字典
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            #提供註解行
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
                update_message(f"⚠ 找不到模組 {module_name}")
        else:
            expanded.append(condition + step)
    return expanded

def analysis_img_order(step):
    required_text = False
    image_part = step
    target_index = 1   # 預設第 1 個

    if image_part.endswith(("?", "↑")):
        image_part = image_part[:-1]

    match = re.match(r'(.+?)@(.+)', image_part)
    if match:
        image_part = match.group(1)
        required_text = match.group(2)

    match = re.match(r'(.+?)#(\-?\d+)', image_part)
    if match:
        image_part = match.group(1)
        target_index = int(match.group(2))

    return image_part, target_index, required_text

def backup_plan_and_timeOut(step):
    backup_plan = "Next"
    timeout = 15
    if "?" in step:
        backup_plan = "ignore"
        timeout = 1.2
    if "↑" in step:
        backup_plan = "Previous"
        timeout = 0.6
    return backup_plan,timeout


def update_message(text, win_name="cmd"):
    """
    將訊息傳給 UI (使用 TCP Socket)
    """
    host = "127.0.0.1"
    port = 5201

    try:
        message = json.dumps({
            "win_name": win_name,
            "message": text
        })

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((host, port))
            s.sendall(message.encode("utf-8"))

    except Exception as e:
        print(f"❌ 傳訊息給 UI 失敗: {e}")



@dataclass
class WaitImageTask:
    step: str
    folder_path: str

    timeout: float = 15
    mode: str = "normal"
    backup_plan: str = "Next"
    wait_forever: bool = False

    thread_event: threading.Event = None
    on_done: callable = None


def find_target_img(full_path, target_index, required_text,thread_event,on_done=None):
    img = cv2.imdecode(np.fromfile(full_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    try:
        locations = list(pyautogui.locateAllOnScreen(img, confidence=0.8))
    except :
        locations = []
    if not locations:
        if on_done : on_done(None)
        return
    if target_index < 0 : target_index + len(locations)
    if target_index > len(locations):
        update_message(f"⚠ 找到 {len(locations)} 個，但沒有第 {target_index} 個")
        if on_done : on_done(None)
        return
    # 不需要文字匹配，直接取目標
    if not required_text:
        loc = locations[target_index - 1]
        if loc : 
            if on_done: on_done(pyautogui.center(loc))
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
            update_message("⚠️ OCR逾時")
            return
        text = re.sub(r'\s+', '', text)
        update_message(f"📄 OCR辨識結果: {text}")
        with lock:
            if thread_event.is_set():
                return
            if required_text in text:
                update_message("✅ OCR 匹配成功")
                if on_done: on_done(pyautogui.center(loc))
                return 
            pending -= 1
            if pending == 0:
                update_message("❌ 所有 OCR 完成，沒有匹配")
                if on_done: on_done(None)
                return

    for loc in locations:
        t = threading.Thread(target=ocr_task, args=(loc,), daemon=True)
        t.start()
  

# 執行模組/指令
def execute_command(command_name, commands, folder_path):
    update_message(f"開始執行 '{command_name}'",folder_path)
    if command_name not in commands:
        update_message(f"❌ 找不到指令 {command_name}",folder_path)
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
                time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                save_commands(command_name,time, record_path)
            else:
                update_message(f"相差天數小於{delta.days}，不執行指令")
                return
    
    def check(index,backup_plan):
        NEXT_EVENT.clear()
        if index >= len(steps):
            update_message(f"{command_name}指令已完成",folder_path)
            return

        if STOP_EVENT.is_set():
            update_message(f"⛔ 偵測到 ESC, {command_name}指令中斷",folder_path)
            return

        if PAUSE_EVENT.is_set() or backup_plan == "Pause":
            update_message(f"{steps[index]} 步驟暫停",folder_path)
            pause_script(lambda : check(max(index-1, 0),"Next"))
            # 等待使用者解除暫停後再呼叫 check
            return
        if backup_plan == "Previous":
            index -= 2
        # 執行當前步驟，完成後自動呼叫下一步
        execute_one_step(
            steps[index],
            folder_path,
            on_done=lambda backup_plan="Next": check(index + 1, backup_plan)
        )

    # 從第一步開始
    check(0,"Next")

# 等待到某個時間點
def wait_until_time(target_time, on_done=None):
    """
    在 agent_core 中等待到 target_time
    可被 NEXT_EVENT 中止
    """
    while True:
        now = datetime.now()
        remaining = (target_time - now).total_seconds()

        if NEXT_EVENT.is_set():
            update_message("⏹ NEXT_EVENT 被觸發，中止等待")
            if on_done:
                on_done()
            return

        if remaining <= 0:
            if on_done:
                on_done()
            return

        # 調整 sleep 精度
        if remaining > 60:
            timeout = 1.0  # 超過 1 分鐘 → 每 1 秒檢查一次
        else:
            timeout = 0.2  # 最後 1 分鐘 → 每 0.2 秒檢查一次

        # 可被中斷
        NEXT_EVENT.wait(timeout)
       
    

def wait_seconds(seconds,folder_path, on_done=None):
    """
    Agent Core 可用的等待秒數
    - seconds: 等待秒數
    - on_done: 完成後 callback
    - ui_queue: 可選，傳訊息給 UI
    """
    global WAIT_TOKEN
    token = uuid.uuid4()
    WAIT_TOKEN = token

    start = time.time()

    while True:
        # ❌ 避免非本輪等待干擾
        if WAIT_TOKEN != token:
            update_message("❌ 不是目前這一輪，直接中止")
            return

        elapsed = time.time() - start

        if NEXT_EVENT.is_set():
            if on_done:
                on_done()
            update_message("⏹ NEXT_EVENT 被觸發，中止等待")
            return

        remaining = max(0, seconds - elapsed)
        update_message((f"⏱ 還剩 {remaining:.1f} 秒...",),folder_path)

        if elapsed >= seconds:
            if on_done:
                on_done()
            return

        # 可中斷等待
        NEXT_EVENT.wait(timeout=0.1)

def wait_button(button, on_done=None):
    """
    等待使用者按鍵 (keyboard)
    - button: 要等待的按鍵名稱，例如 'esc'
    - on_done: 完成後 callback
    - ui_queue: 可選，用於回報訊息給 UI
    """
    while True:
        if NEXT_EVENT.is_set() or keyboard.is_pressed(button):
            if on_done: on_done()
            return
        NEXT_EVENT.wait(timeout=0.1)  # 可被中斷

def wait_mouse(button, on_done=None):
    """
    等待使用者按滑鼠
    - button: 'left' 或 'right'
    """
    while True:
        if NEXT_EVENT.is_set() or mouse.is_pressed(button):
            if on_done: on_done()
            return
        NEXT_EVENT.wait(timeout=0.1)  # 可被中斷
        
def execute_one_step(step,folder_path,on_done=None):
    update_message(step)
    def image_click(center,backup_plan,mode="normal"):
        if center != False:
            try:
                ctypes.windll.user32.BlockInput(True)
                # move + click
                if mode != "wait" :
                    pyautogui.moveTo(center)
                    if mode != "move" :
                        pyautogui.click()
            finally:
                ctypes.windll.user32.BlockInput(False)
            #避免過快點擊出現的按鈕
        if on_done : on_done(backup_plan)
    # 判斷是否定時執行
    # 假設 step 是像 "wait_14:30" 或 "wait_02:05" 這樣的字串
    # 在 excuse_one_step 裡替換
    if step == 'exitCommand' :  return
    if step == 'nextCommand' :  
        if on_done: on_done()
        return
    #---------------搶票用--------------
    if re.match(r'wait_?\d{1,2}:\d{2}', step):
        target_time_str = re.findall(r'wait_?(\d{1,2}:\d{2})', step)[0]
        now = datetime.now()
        target_time = datetime.strptime(target_time_str, "%H:%M").replace(
            year=now.year, month=now.month, day=now.day
        )
        if target_time < now:
            target_time += timedelta(days=1)
        update_message(f"⏱ 等待至 {target_time.strftime('%Y-%m-%d %H:%M:%S')} (搶票模式)")
        wait_until_time(target_time,on_done)
        return
    if re.match(r'waitPress->(.+)', step):
        button = re.match(r'waitPress->(.+)', step).group(1)
        update_message(f"⏱ 等待 {button} 按鍵")
        wait_button(button,on_done)
        return
    if re.match(r'waitMouse->(.+)', step):
        button = re.match(r'waitMouse->(.+)', step).group(1)
        update_message(f"⏱ 等待滑鼠 {button} 按鍵")
        wait_mouse(button,on_done)
        return
    # 判斷有無文字輸入需求
    if re.match(r'"(.+)"', step):
        text = re.match(r'"(.+)"', step).group(1)
        pyperclip.copy(text)
        time.sleep(0.1)
        pyautogui.hotkey("ctrl", "v")
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
    if step == 'rightClick':
        # 按一下滑鼠左鍵
        pyautogui.rightClick()
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
        update_message(f"⏱ 等待 {seconds} 秒")
        wait_seconds(seconds,folder_path,on_done)
        return
    if step in ("scrollUp", "scrollDown"):
        pyautogui.scroll(500 if step == "scrollUp" else -500)
        if on_done:on_done()
        return
    if step.startswith(("http://", "https://")):
        launch_webdriver(step)
        if on_done:on_done()
        return
    if step.startswith("dmmgameplayer://") or ".lnk" in step:
        launch_app(step)
        if on_done:on_done()
        return
    # 判斷其他條件    
    if re.match(r'(\w+)-(\w+)->(.+)', step):            
        check_condition(step,folder_path,on_done)
        return
    if re.match(r'minimize->(.+)', step):
        processName = re.match(r'minimize->(.+)', step).group(1)
        update_message(f"最小化{processName}視窗")
        minimize_my_game_window(processName)
        if on_done:on_done()
        return
    # 判斷or條件 
    backup_plan,timeout = backup_plan_and_timeOut(step)
    mode="normal"
    wait_forever = False
    match = re.match(r'waitImg->(.+)', step)
    if match:
        wait_forever = True
        timeout = 0
        mode="wait"
        step = match.group(1)
    match = re.match(r'move->(.+)', step)
    if match:
        mode="move"
        step = match.group(1)
    if "|" in step:
        steps = [s.strip() for s in step.split("|") if s.strip()]
    else:
        steps = [step]
    thread_event = threading.Event()
    for s in steps:
        task = WaitImageTask(
        step=s,
        folder_path=folder_path,
        timeout=timeout,
        mode=mode,
        backup_plan=backup_plan,
        wait_forever=wait_forever,
        thread_event=thread_event,
        on_done=image_click
        )
        t = threading.Thread(
            target=wait_until_image,
            args=(task,),
            daemon=True
        )
        t.start()


def pause_script(on_done):
    PAUSE_EVENT.clear()
    wait_button("space",on_done)
    
            
def check_condition(step,folder_path,on_done=None):
    def condition_noimage(center):
        if center is None : 
            update_message(f"沒有找到圖片{image_part}.png,不執行指令{order}")
            if on_done : on_done()
            return False
        NEXT_EVENT.clear()
        execute_one_step(order,folder_path,on_done)
    
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
        if conditionValue in WEEK_MAP_ORDER:
            index = WEEK_MAP_ORDER.index(conditionValue)
            if conditionValue != day : 
                update_message(f"今天不是{WEEK_MAP[index]},不執行指令{order}")
                if on_done : on_done("Next")
                return
            execute_one_step(order,folder_path,on_done)
        else:
            update_message("星期縮寫有誤，請輸入Mon,Tue,Wed,Thu,Fri,Sat,Sun")
    elif condition == "date"  :
        day = datetime.now().day
        if int(conditionValue) != day : 
            update_message(f"今天不是{conditionValue}號,不執行指令{order}")
            if on_done : on_done("Next")
            return
        execute_one_step(order,folder_path,on_done)
    elif condition == "img"  :
        image_part, target_index, required_text = analysis_img_order(conditionValue)
        full_path = os.path.join(folder_path, f"{image_part}.png")
        thread_event = threading.Event()
        find_target_img(full_path, target_index, required_text,thread_event,condition_noimage)            
    else:
        update_message(f"條件設定有誤,不執行指令{order}")
        if on_done : on_done()

def enter_captcha(step, folder_path,on_done):
    # 先拆 @-> 判斷文字需求
    match = re.match(r'(.+?)@->(.+)#(\d)', step)
    if not match:
        update_message(f"❌ 格式錯誤: {step}")
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
        update_message(f"❌ 找不到圖片 {match.group(2)}.png")
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
        update_message(f"📄 OCR辨識結果: {text}")
        # 用#來判斷要輸入幾碼
        if len(text) == count :
            break
    # 找輸入框圖片並輸入
    img = cv2.imdecode(np.fromfile(input_box_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    try:
        input_matches = list(pyautogui.locateAllOnScreen(img, confidence=0.8))
    except Exception:
        input_matches = []
    if not input_matches:
        update_message(f"❌ 找不到圖片 {match.group(1)}.png")
        return False

    loc = input_matches[0] 
    center = pyautogui.center(loc)

    # 先移動滑鼠，再點擊
    pyautogui.moveTo(center)
    pyautogui.click()
    pyautogui.write(text)  # 立即輸入所有文字
    if on_done: on_done()

def wait_until_image(task: WaitImageTask):
    step = task.step
    folder_path = task.folder_path
    timeout = task.timeout
    mode = task.mode
    backup_plan = task.backup_plan
    wait_forever = task.wait_forever
    thread_event = task.thread_event
    on_done = task.on_done
    """非阻塞等待圖片，找到後呼叫 on_done(result)"""

    image_part, target_index, required_text = analysis_img_order(step)
    full_path = os.path.join(folder_path, f"{image_part}.png")
    # ✅ 檢查檔案是否存在
    if not os.path.exists(full_path):
        update_message(f"❌ 找不到檔案: {full_path}")
        if on_done :on_done(False,"Pause")
        return 
    if target_index > 0 :
        update_message(f"🔍 等待圖片：{image_part}.png (目標第 {target_index} 個)",folder_path)
    else:
        update_message(f"🔍 等待圖片：{image_part}.png (目標倒數第 {target_index * -1} 個)",folder_path)
    
    start = time.time()
    def callback(center):
        """子線程找到圖片就會呼叫"""
        if thread_event.is_set():
            return
        if NEXT_EVENT.is_set():
            thread_event.set()
            if on_done : on_done(False,"Next",mode)
            return        
        if center:
            update_message(f"✅ 找到 {image_part}.png",folder_path)
            thread_event.set()
            if on_done: on_done(center, "Next", mode)
            return
        if time.time() - start >= timeout and not wait_forever:
            update_message(f"⏳ 等待 {image_part}.png 超時 {timeout} 秒")
            thread_event.set()
            if backup_plan == "Next": PAUSE_EVENT.set()
            if on_done: on_done(False, backup_plan)
            return
        NEXT_EVENT.wait(timeout=0.1)
        find_target_img(full_path, target_index, required_text, thread_event, callback)

    # 單次呼叫，所有 OCR 都在子線程
    find_target_img(full_path, target_index, required_text, thread_event, callback)



def launch_webdriver(url):
    # 打開一個網頁
    update_message(" 開啟網頁 " + url)
    # 開啟指定網址（使用預設瀏覽器）
    webbrowser.open_new_tab(url)   
def launch_app(url):
    subprocess.run(["start", url], shell=True)


def minimize_my_game_window(processName):
    def enum_handler(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return

        title = win32gui.GetWindowText(hwnd)
        if processName in title:
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
            update_message(f"已最小化視窗: {title}")

    win32gui.EnumWindows(enum_handler, None)


def start_socket_server():
    host = "127.0.0.1"
    port = 5200   # 給 UI 連線的 port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind((host, port))
        server.listen(5)

        print(f"✅ Socket Server 啟動中... {host}:{port}")

        while True:
            conn, addr = server.accept()
            with conn:
                try:
                    data = conn.recv(64 * 1024)
                    if not data:
                        continue

                    message = data.decode("utf-8").strip()
                    data = json.loads(message)

                    folder_path = data.get("folder")
                    command_name = data.get("command")

                    if not folder_path or not command_name:
                        print("❌ 收到無效訊息:", data)
                        continue

                    commands_file = os.path.join(folder_path, "commands.txt")
                    commands = load_commands(commands_file)

                    if command_name in commands:
                        print(f"執行指令: {command_name} 在資料夾 {folder_path}")
                        execute_command(command_name, commands, folder_path)
                    else:
                        print(f"❌ 指令不存在: {command_name}")

                except json.JSONDecodeError:
                    print("❌ 收到非 JSON 訊息")
                except Exception as e:
                    print(f"❌ 處理錯誤: {e}")


if __name__ == "__main__":
    start_socket_server()