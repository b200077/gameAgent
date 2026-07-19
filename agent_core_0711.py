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

import psutil


# 確保目前目錄就是腳本位置
os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))


BASE_PATH = '.'
WEEK_MAP= ["星期一","星期二","星期三","星期四","星期五","星期六","星期日"]
WEEK_MAP_ORDER= ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]

CONFIG_PATH = os.path.join(BASE_PATH, "config.json")
DEFAULT_CONFIG = {
    "timeout_normal": 15,        # 一般等待圖片超時秒數
    "timeout_skip": 1.0,         # ? 模式超時秒數
    "timeout_retry": 0.4,        # ↑ 模式超時秒數
    "poll_interval_medium": 0.2, # timeout<=2.0 時的輪詢間隔
    "poll_interval_normal": 0.6, # 一般輪詢間隔
}

def load_config(path):
    """讀取 config.json，缺檔或缺值都用預設值補上，並寫回檔案"""
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                config.update(json.load(f))
        except Exception as e:
            print(f"⚠ config.json 讀取失敗，使用預設值: {e}")
    else:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"⚠ 無法建立 config.json: {e}")
    return config

CONFIG = load_config(CONFIG_PATH)

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

def expand_steps(steps, commands, condition="", args=None):
    if args is None:
        args = []

    expanded = []
    mulExpanded = []

    # ⭐ 1. 展開 * 次數
    for step in steps:
        # ⭐ 2-1 參數替換 ($1, $2...)
        def replace_arg(match):
            index = int(match.group(1)) - 1
            return args[index] if index < len(args) else match.group(0)

        step = re.sub(r'\$(\d+)', replace_arg, step)
        match = re.match(r'(.+)\*(\d+)$', step)
        if match:
            order, count = match.groups()
            for _ in range(int(count)):
                mulExpanded.append(order.strip())
        else:
            mulExpanded.append(step)

    # ⭐ 2. 處理每個 steps
    for step in mulExpanded:
        # ⭐ 2-2 判斷是否為模組
        if "->:" in step or step.startswith(":"):
            stepCondition, module_call = step.split(":", 1)

            # ⭐ 解析 moduleName$arg1$arg2
            parts = module_call.split("$")
            module_name = parts[0]
            module_args = parts[1:] if len(parts) > 1 else []

            new_condition = condition if condition else stepCondition

            if module_name in commands:
                expanded.extend(
                    expand_steps(
                        commands[module_name],
                        commands,
                        new_condition,
                        module_args
                    )
                )
            else:
                update_message(f"⚠ 找不到模組 {module_name}")

        else:
            expanded.append(condition + step)

    return expanded

def analysis_img_order(step,folder_path):
    required_text = False
    image_part = step
    target_index = 1
    size = 1.0

    if image_part.endswith(("?", "↑", "✓")):
        image_part = image_part[:-1]

    # 一次找出所有 @xxx #xxx %xxx 片段（任意順序）
    tokens = re.findall(r'[@#%][^@#%]+', image_part)
    # 移除所有 token，剩下的就是檔名
    image_part = re.sub(r'[@#%][^@#%]+', '', image_part)

    for token in tokens:
        if token.startswith('@'):
            required_text = token[1:]
        elif token.startswith('#'):
            target_index = int(token[1:])
        elif token.startswith('%'):
            size = float(token[1:])
    return ImgOrderResult(folder_path,image_part, target_index, required_text, size)

def backup_plan_and_timeOut(step):
    backup_plan = "Next"
    timeout = CONFIG["timeout_normal"]
    if "?" in step:
        backup_plan = "ignore"
        timeout = CONFIG["timeout_skip"]
    if "↑" in step:
        backup_plan = "Previous"
        timeout = CONFIG["timeout_retry"]
    if "✓" in step:
        backup_plan = "Ensure"
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
    lock: threading.Lock = None   # ← 新增
    on_done: callable = None

@dataclass
class ImgOrderResult:
    folder_path: str
    image_part: str
    target_index: int
    required_text: str | bool
    size: float

def apply_nms(locations, overlap_thresh=0.3):
    if not locations:
        return []
    # 轉成 (x1, y1, x2, y2) 格式
    boxes = [(l.left, l.top, l.left + l.width, l.top + l.height, l) for l in locations]
    keep = []
    while boxes:
        best = boxes.pop(0)
        keep.append(best[4])  # 保留原始 location 物件
        boxes = [b for b in boxes if not (
            min(best[2], b[2]) - max(best[0], b[0]) > 0 and
            min(best[3], b[3]) - max(best[1], b[1]) > 0
        )]
    return keep
def scale_image(img, scale):
    h, w = img.shape[:2]
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    return cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=interp)

def find_target_img(imgOrder,thread_event,on_done=None):
    full_path = os.path.join(imgOrder.folder_path, f"{imgOrder.image_part}.png")
    print(full_path)
    img = cv2.imdecode(np.fromfile(full_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    print("size=" + str(imgOrder.size))
    if imgOrder.size != 1.0:
        img = scale_image(img, imgOrder.size)
    try:
        locations = list(pyautogui.locateAllOnScreen(img, confidence=0.8))
    except Exception as e:
        #print(f"❌ 處理錯誤: {e}")
        locations = []
    # ← NMS 過濾重疊位置
    locations = apply_nms(locations)
    if not locations:
        if on_done : on_done(None)
        return
    if imgOrder.target_index < 0 : imgOrder.target_index += len(locations)+1
    if imgOrder.target_index > len(locations):
        update_message(f"⚠ 找到 {len(locations)} 個，但沒有第 {imgOrder.target_index} 個")
        if on_done : on_done(None)
        return
    # 不需要文字匹配，直接取目標
    if not imgOrder.required_text:
        loc = locations[imgOrder.target_index - 1]
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
            if match_ocr_value(text, imgOrder.required_text):
                update_message("✅ OCR 匹配成功")
                if on_done: on_done(pyautogui.center(loc))
                return 
            pending -= 1
            if pending == 0:
                update_message("❌ 所有 OCR 完成，沒有匹配")
                if on_done: on_done(None)
                return
            
    print(len(locations))
    for loc in locations:
        t = threading.Thread(target=ocr_task, args=(loc,), daemon=True)
        t.start()

def match_ocr_value(ocr_text, required_text):
    # 提取 OCR 裡的數字
    ocr_num = re.search(r'\d+\.?\d*', ocr_text)
    
    # 嘗試解析運算符
    match = re.match(r'([><=!]=?)(\d+\.?\d*)', required_text)
    
    if match and ocr_num:
        op = match.group(1)
        target = float(match.group(2))
        value = float(ocr_num.group())
        ops = {'>': lambda a,b: a>b, '<': lambda a,b: a<b,
               '>=': lambda a,b: a>=b, '<=': lambda a,b: a<=b,
               '==': lambda a,b: a==b, '!=': lambda a,b: a!=b}
        return ops[op](value, target)
    
    # 沒有運算符，維持原本字串包含比對
    return required_text in ocr_text  

# 執行模組/指令
def execute_command(command_name, commands, folder_path):
    update_message(f"開始執行 '{command_name}'",folder_path)
    if command_name not in commands:
        update_message(f"❌ 找不到指令 {command_name}",folder_path)
        return

    STOP_EVENT.clear()
    PAUSE_EVENT.clear()

    steps = expand_steps(commands[command_name], commands)
    # 這裡檢查第一層參數輸入正不正確
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
        if backup_plan.lower().startswith('callcommand:'):
            comName = re.match(r'callcommand:(.+)', backup_plan).group(1)
            execute_command(comName, commands, folder_path)
            return
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
        match backup_plan:
            case "Previous"|"Ensure":
                index -= 2
            case "skipNext":
                index += 1        
        
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
        update_message(f"⏱ 還剩 {remaining:.1f} 秒...",folder_path)

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
    if not step or not step.strip():   # ← 加這行
        if on_done: on_done()          # ← 加這行，空步驟直接跳下一步
        return                         # ← 加這行
    update_message(step)
    def image_click(center,backup_plan,mode="normal"):
        if center != False:
            if mode != "wait" :
                pyautogui.moveTo(center)
                if mode != "move" :
                    pyautogui.click()
        else:
            if backup_plan == "Ensure" : backup_plan="Next"
        if on_done : on_done(backup_plan)
    # 判斷是否定時執行
    # 假設 step 是像 "wait_14:30" 或 "wait_02:05" 這樣的字串
    # 在 excuse_one_step 裡替換
    if step.lower() == 'exitcommand' :  return
    if step.lower() == 'nextcommand' :  
        if on_done: on_done("skipNext")
        return
    if step.lower().startswith('callcommand:'):  
        if on_done: on_done(step)
        return
    #---------------搶票用--------------
    if re.match(r'wait\d{1,2}:\d{2}', step):
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
    # if re.match(r'waitMouse->(.+)', step):
    #     button = re.match(r'waitMouse->(.+)', step).group(1)
    #     update_message(f"⏱ 等待滑鼠 {button} 按鍵")
    #     wait_mouse(button,on_done)
    #     return
    if step.lower() == 'waitclick':
        # 按一下滑鼠左鍵
        update_message(f"⏱ 等待滑鼠左鍵")
        wait_mouse("left",on_done)
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
    if step.lower() == 'mouseclick':
        # 按一下滑鼠左鍵
        pyautogui.click()
        if on_done: on_done()
        return
    if step.lower() == 'rightclick':
        # 按一下滑鼠右鍵
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
    cmdKeyWord = ["dmmgameplayer://",".lnk",".exe","browndust2:"]
    if any(kw in step for kw in cmdKeyWord):
        launch_app(step)
        if on_done: on_done()
        return
    # 判斷其他條件    
    if re.search(r'(\w+)-(\w+)->(.+)', step):            
        check_condition(step,folder_path,on_done)
        return
    if re.match(r'minimize->(.+)', step):
        processName = re.match(r'minimize->(.+)', step).group(1)
        update_message(f"最小化{processName}視窗")
        control_game_window(processName,"min")
        if on_done:on_done()
        return
    if re.match(r'focus->(.+)', step):
        processName = re.match(r'focus->(.+)', step).group(1)
        control_game_window(processName,"focus")
        if on_done: on_done()
        return
    if re.match(r'close->(.+)', step):
        processName = re.match(r'close->(.+)', step).group(1)
        control_game_window(processName,"close")
        if on_done: on_done()
        return
    if re.match(r'match->(.+)', step):
        image_name = re.match(r'match->(.+)', step).group(1)
        calibrate_match(image_name, folder_path, on_done)
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
    _lock = threading.Lock()  # ← 跟 thread_event 同層建立
    for s in steps:
        task = WaitImageTask(
        step=s,
        folder_path=folder_path,
        timeout=timeout,
        mode=mode,
        backup_plan=backup_plan,
        wait_forever=wait_forever,
        thread_event=thread_event,
        lock=_lock,          # ← 傳進去
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

def calibrate_match(image_name, folder_path, on_done=None, duration=15, interval=0.5):
    """視窗校正用：持續印出圖片在目前畫面的匹配率"""
    full_path = os.path.join(folder_path, f"{image_name}.png")
    if not os.path.exists(full_path):
        update_message(f"❌ 找不到檔案: {full_path}")
        if on_done: on_done()
        return

    template = cv2.imdecode(np.fromfile(full_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    start = time.time()

    while time.time() - start < duration:
        if NEXT_EVENT.is_set():
            break
        screenshot = np.array(pyautogui.screenshot())
        screen_img = cv2.cvtColor(screenshot, cv2.COLOR_RGB2BGR)
        result = cv2.matchTemplate(screen_img, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        update_message(f"🎯 {image_name}.png 匹配率: {max_val * 100:.1f}%")
        NEXT_EVENT.wait(timeout=interval)

    if on_done: on_done()
    
            
def check_condition(step,folder_path,on_done=None):
    def condition_noimage(center):
        should_skip = (not reverse and center is None) or (reverse and center)
        if should_skip:
            msg = "沒有找到" if not reverse else "有找到"
            update_message(f"{msg}圖片{imgOrder.image_part}.png,不執行指令{order}")
            if on_done: on_done()
            return False
        NEXT_EVENT.clear()
        execute_one_step(order, folder_path, on_done)    
    condition = None
    order = None
    conditionValue = None
    reverse = False
    # 先拆 -> 判斷條件
    match = re.match(r'(.+)-(.+)->(.+)',step)
    if not match: return False
    condition = match.group(1)
    conditionValue = match.group(2)
    order = match.group(3)
    #week-Sun->free
    if condition.startswith("!"):
        reverse = True
        condition = condition[1:]
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
        imgOrder = analysis_img_order(conditionValue,folder_path)
        thread_event = threading.Event()
        find_target_img(imgOrder,thread_event,condition_noimage)            
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

    imgOrder = analysis_img_order(step,folder_path)
    full_path = os.path.join(folder_path, f"{imgOrder.image_part}.png")
    # ✅ 檢查檔案是否存在
    if not os.path.exists(full_path):
        update_message(f"❌ 找不到檔案: {full_path}")
        if on_done :on_done(False,"Pause")
        return 
    if imgOrder.target_index > 0 :
        update_message(f"🔍 等待圖片：{imgOrder.image_part}.png (目標第 {imgOrder.target_index} 個)",folder_path)
    else:
        update_message(f"🔍 等待圖片：{imgOrder.image_part}.png (目標倒數第 {imgOrder.target_index * -1} 個)",folder_path)
    
    start = time.time()
    def callback(center):
        """子線程找到圖片就會呼叫"""             # ← 用傳進來的共享 lock
        if thread_event.is_set():
            return
        if NEXT_EVENT.is_set():
            with task.lock:  
                thread_event.set()
            if on_done : on_done(False,"Next",mode)
            return        
        if center:
            update_message(f"✅ 找到 {imgOrder.image_part}.png",folder_path)
            with task.lock:  
                thread_event.set()
            if on_done: on_done(center, "Next", mode)
            return
        if time.time() - start >= timeout and not wait_forever:
            update_message(f"⏳ 等待 {imgOrder.image_part}.png 超時 {timeout} 秒")
            with task.lock:  
                thread_event.set()
            if backup_plan == "Next": PAUSE_EVENT.set()
            if on_done: on_done(False, backup_plan)
            return
        interval = get_poll_interval(timeout, wait_forever)
        NEXT_EVENT.wait(timeout=interval)
        find_target_img(imgOrder, thread_event, callback)

    # 單次呼叫，所有 OCR 都在子線程
    find_target_img(imgOrder, thread_event, callback)
    
def get_poll_interval(timeout, wait_forever):
    if wait_forever:
        return 1.0   # waitImg-> 模式，不急
    if timeout <= 0.5:
        return 0.05  # ↑ ? 模式，需要快速反應
    if timeout <= 2.0:
        return CONFIG["poll_interval_medium"]
    return CONFIG["poll_interval_normal"]       # 一般等待，省 CPU



def launch_webdriver(url):
    # 打開一個網頁
    update_message(" 開啟網頁 " + url)
    # 開啟指定網址（使用預設瀏覽器）
    webbrowser.open_new_tab(url)   
def launch_app(url):
    subprocess.run(["start", url], shell=True)

def control_game_window(processName,operate):
    def enum_handler(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return

        title = win32gui.GetWindowText(hwnd)
        if processName in title:
            if operate == "min":
                win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
                update_message(f"已最小化視窗: {title}")
            if operate == "close":
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                update_message(f"已關閉視窗: {title}")
            if operate == "focus":
                if win32gui.IsIconic(hwnd):
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
                update_message(f"已切換至視窗: {title}")

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
                    if command_name == "closeCore":
                        print("🛑 收到關閉指令，Core 即將關閉")
                        conn.close()
                        server.close()
                        os._exit(0)
                    elif command_name in commands:
                        print(f"執行指令: {command_name} 在資料夾 {folder_path}")
                        execute_command(command_name, commands, folder_path)
                    else:
                        print(f"❌ 指令不存在: {command_name}")

                except json.JSONDecodeError:
                    print("❌ 收到非 JSON 訊息")
                except Exception as e:
                    print(f"❌ 處理錯誤: {e}")

def memory_watchdog(max_gb=1, check_interval=5):
    """
    監控記憶體用量，超過 max_gb 就強制終止
    """
    process = psutil.Process(os.getpid())
    while True:
        mem_gb = process.memory_info().rss / (1024 ** 3)
        if mem_gb > max_gb:
            update_message(f"⛔ 記憶體超過 {max_gb}GB ({mem_gb:.1f}GB)，強制終止")
            time.sleep(1)  # 讓訊息送出去
            os.kill(os.getpid(), 9)
        time.sleep(check_interval)

if __name__ == "__main__":
    t = threading.Thread(target=memory_watchdog, args=(1, 5), daemon=True)
    t.start()
    start_socket_server()