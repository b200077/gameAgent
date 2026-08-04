import json
import os
from datetime import datetime, timedelta
import calendar

FILE_NAME = "schedule.json"

# -----------------------
# 基本功能
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
# 新增
# -----------------------
def add_task(data):
    user_input = input("輸入（格式：日期 內容）：")

    if " " not in user_input:
        print("格式錯誤")
        return

    date_str, task = user_input.split(" ", 1)
    dates = parse_dates(date_str)

    for d in dates:
        if d not in data:
            data[d] = []
        data[d].append(task)

    save_data(data)
    print("✅ 已儲存")

# -----------------------
# 刪除
# -----------------------
def delete_task(data, user_input):
    user_input = input("輸入（格式：del 關鍵字 日期）：").strip()

    parts = user_input.split()

    if len(parts) < 2:
        print("格式錯誤")
        return

    keyword = parts[0]
    date_str = parts[1]

    dates = parse_dates(date_str)

    for d in dates:
        if d not in data:
            continue

        original_len = len(data[d])

        # 🔥 刪除包含關鍵字的任務
        data[d] = [task for task in data[d] if keyword not in task]

        removed_count = original_len - len(data[d])

        if removed_count > 0:
            print(f"🗑️ {d} 刪除 {removed_count} 筆（關鍵字：{keyword}）")

        if not data[d]:
            del data[d]

    save_data(data)

# -----------------------
# 主程式
# -----------------------
def main():
    data = load_data()

    # 顯示今天
    today = get_today()
    print(f"📅 今天 ({today})")
    show_dates(data, today)

    while True:
        cmd = input("\n指令 (add / show / del / exit)：")

        if cmd == "add":
            add_task(data)
        elif cmd.startswith("show"):
            _, *rest = cmd.split()
            if rest:
                show_dates(data, rest[0])
        elif cmd.startswith("del"):
            _, *rest = cmd.split(maxsplit=2)
            if len(rest) >= 2:
                delete_task(data, " ".join(rest))
        elif cmd == "exit":
            break

if __name__ == "__main__":
    main()