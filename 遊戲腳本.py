import os
import sys
import pyautogui
import time
import re
import pyscreeze
import keyboard
import pytesseract
import difflib
from pyscreeze import ImageNotFoundException

# 確保目前目錄就是腳本位置
os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))

BASE_PATH = '.'

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

# 展開模組（防止循環依賴）
def expand_steps(steps, commands, visited=None):
    if visited is None:
        visited = set()
    expanded = []
    for step in steps:
        if step.startswith(":"):
            module_name = step[1:]
            if module_name in visited:
                print(f"⚠ 循環依賴偵測：{module_name} 已展開過")
                continue
            if module_name in commands:
                visited.add(module_name)
                expanded.extend(expand_steps(commands[module_name], commands, visited))
            else:
                print(f"⚠ 找不到模組 {module_name}")
        else:
            expanded.append(step)
    return expanded

# 全域旗標
STOP_EXECUTION = False

def esc_pressed():
    global STOP_EXECUTION
    STOP_EXECUTION = True
    print("\n⛔ 偵測到 ESC，中斷所有指令並返回選單")

keyboard.add_hotkey('esc', esc_pressed, suppress=False)

def find_and_click_with_text(step, folder_path):
    # 分析 step 格式: image#text
    target_index = 1
    required_text = None
    image_part = step
    # 先拆 @ 判斷文字需求
    match = re.match(r'(.+?)@(.+)',image_part)
    if match:
        image_part = match.group(1)
        required_text = match.group(2)
    # 再拆 # 判斷目標第幾個
    match = re.match(r'(.+?)#(\d+)', image_part)
    if match:
        image_part = match.group(1)
        target_index = int(match.group(2))

    full_path = os.path.join(folder_path, f"{image_part}.png")
    print(f"🔍 尋找圖片：{image_part}.png (目標第 {target_index} 個)")

    # 找圖片
    try:
        locations = list(pyautogui.locateAllOnScreen(full_path, confidence=0.8))
    except Exception:
        locations = []
    if not locations:
        print(f"❌ 找不到圖片 {image_part}.png")
        return False
    if target_index > len(locations):
        print(f"⚠ 找到 {len(locations)} 個，但沒有第 {target_index} 個")
        return False
    loc = locations[target_index - 1] 
    center = pyautogui.center(loc)
    region = (int(loc.left), int(loc.top), int(loc.width), int(loc.height))
    if required_text:
        for loc in locations :
            center = pyautogui.center(loc)
            region = (int(loc.left), int(loc.top), int(loc.width), int(loc.height))
            screenshot = pyautogui.screenshot(region=region)
            text = pytesseract.image_to_string(screenshot, lang="chi_tra+eng+jpn").strip()
            text = re.sub(r'\s+', '', text)
            print(f"📄 OCR辨識結果: {text}")
            if required_text in text: break
        if not required_text :
            print(f"❌ OCR文字不匹配: 需要 '{required_text}'")
            return False

    # 先移動滑鼠，再點擊
    pyautogui.moveTo(center)
    pyautogui.click()
    print(f"✅ 點擊 {image_part}.png 第 {target_index} 個 (文字匹配: {required_text})")
    return True

# 執行模組/指令
def execute_command(command_name, commands, folder_path):
    global STOP_EXECUTION
    STOP_EXECUTION = False

    if command_name not in commands:
        print(f"❌ 找不到指令 {command_name}")
        return
    steps = expand_steps(commands[command_name], commands)
    for step in steps:
        if STOP_EXECUTION:
            print("⛔ 已中斷執行")
            break

        if re.match(r'wait_?(\d+(\.\d+)?)', step):
            seconds = float(re.findall(r'wait_?(\d+(\.\d+)?)', step)[0][0])
            print(f"⏱ 等待 {seconds} 秒")
            for _ in range(int(seconds * 10)):
                if STOP_EXECUTION:
                    break
                time.sleep(0.1)
        elif step in ("scrollUp", "scrollDown"):
            pyautogui.scroll(500 if step == "scrollUp" else -500)
        else:
            # 點擊或等待圖片
            success = find_and_click_with_text(step, folder_path)
            if not success and not STOP_EXECUTION:
                wait_until_image(step, folder_path)
                if not STOP_EXECUTION:
                    find_and_click_with_text(step, folder_path)

            
def wait_until_image(step, folder_path, timeout=10):
    global STOP_EXECUTION
    start_time = time.time()
    # 預設
    ocr_text = None
    target_index = 1
    # 解析 step，把 @後面的 OCR 文字去掉
    # 先用 @ 分割 OCR 文字（如果有）
    if '@' in step:
        image_part = step.split('@', 1)[0]
    else:
        image_part = step

    # 再用 # 分割目標索引（如果有）
    if '#' in image_part:
        image_name, index_str = image_part.split('#', 1)
        try:
            target_index = int(index_str)
        except ValueError:
            target_index = 1
    else:
        image_name = image_part

    full_path = os.path.join(folder_path, f"{image_name}.png")
    print(f"🔍 等待圖片：{image_name}.png (目標第 {target_index} 個)")

    while not STOP_EXECUTION:
        try:
            locations = list(pyautogui.locateAllOnScreen(full_path, confidence=0.8))
        except pyscreeze.ImageNotFoundException:
            locations = []
        except OSError:
            print(f"❌ 圖片檔案不存在或無法讀取: {full_path}")
            return None

        if locations:
            if target_index <= len(locations):
                location = pyautogui.center(locations[target_index - 1])
                print(f"✅ 找到 {image_name}.png 第 {target_index} 個 at {location}")
                return location
            else:
                print(f"⚠ 找到 {len(locations)} 個，但沒有第 {target_index} 個")

        if time.time() - start_time > timeout:
            print(f"⏳ 等待 {image_name}.png 超時 {timeout} 秒")
            return None

        time.sleep(0.05)

    return None

# 子選單
def command_menu(game_folder):
    folder_path = os.path.join(BASE_PATH, game_folder)
    while True:
        commands = load_commands(os.path.join(folder_path, "commands.txt"))
        if not commands:
            return

        keys = list(commands.keys())
        print(f"\n🎮 遊戲：{game_folder}")
        for idx, key in enumerate(keys, 1):
            print(f"{idx}. {key}: {commands[key]}")
        user_input = input("輸入指令編號或名稱（直接按 Enter 返回）：").strip()
        if user_input == '':
            return
        if user_input.isdigit():
            idx = int(user_input) - 1
            if 0 <= idx < len(keys):
                key = keys[idx]
                print(f"🕒 3秒後開始執行 '{key}'")
                time.sleep(3)
                execute_command(key, commands, folder_path)
            else:
                print("❌ 編號錯誤")
        else:
            if user_input in commands:
                print(f"🕒 3秒後開始執行 '{user_input}'")
                time.sleep(3)
                execute_command(user_input, commands, folder_path)
            else:
                print("❌ 指令名稱錯誤")

# 主選單
def main_menu():
    while True:
        print("\n📂 遊戲清單：")
        folders = [f for f in os.listdir(BASE_PATH) if os.path.isdir(os.path.join(BASE_PATH, f))]
        for idx, folder in enumerate(folders):
            print(f"{idx + 1}. {folder}")
        user_input = input("輸入：").strip()
        if user_input.isdigit():
            idx = int(user_input) - 1
            if 0 <= idx < len(folders):
                game_folder = folders[idx]
                command_menu(game_folder)
            else:
                print("❌ 編號錯誤")
        else:
            print("❌ 請輸入數字")

if __name__ == "__main__":
    main_menu()
