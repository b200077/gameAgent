# GameAgent

以圖像辨識為核心的 Windows 桌面自動化工具，用於手機模擬器 / PC 遊戲的日常任務自動化（簽到、領獎、搶票等重複性操作），不修改遊戲檔案或記憶體。

## 核心概念

不使用固定座標，而是用截圖比對畫面上的按鈕/圖示位置，因此：

- 遊戲視窗不需要固定在特定位置，只要長寬比例與截圖一致即可
- 腳本只需維護「資料夾（一款遊戲）+ 圖片 + commands.txt」即可運作，降低重工

```
game_folder/
├─ commands.txt      # 自動化腳本
└─ *.png             # UI 元素截圖
```

## 架構

雙進程設計：

- **agent_ui.py**：CustomTkinter 前端，操作介面、指令按鈕、訊息顯示
- **agent_core.py**（PyInstaller 打包為 agent_core.exe）：實際執行圖像辨識與自動化邏輯

兩者透過本機 TCP Socket 溝通：

| 方向 | Port | 用途 |
|---|---|---|
| UI → Core | 5200 | 傳送要執行的指令 / 資料夾 / 參數 |
| Core → UI | 5201 | 回傳執行訊息、狀態更新 |

## 主要特性

- **圖像辨識點擊**：`pyautogui` + `cv2.matchTemplate`，支援多結果偵測與 NMS 去重疊
- **OCR 輔助判斷**：`pytesseract`（繁中/英/日），可用於防止誤判相同外觀的不同按鈕，並支援數值比較（`>`、`<`、`>=`、`<=`、`==`、`!=`）
- **驗證碼辨識**：`@->` 指令，OCR 辨識指定碼數後自動輸入
- **自訂 DSL**：模組化、參數化、多種流程控制符號（詳見下方指令表）
- **平行偵測**：`|` 同時等待多張圖片，任一符合即觸發
- **視窗校正模式**：`match->圖片名稱` 持續 15 秒、每 0.5 秒印出比對信心分數，協助排查解析度/縮放誤差（刻意不做多尺度校正，才能看出真實落差）
- **未使用圖片檢查**：掃描 commands.txt 找出未被引用的 png，可一鍵刪除
- **逾時恢復機制**：逾時後依序嘗試 → 檢查視窗 → 重點前一張圖 → （AI 視覺輔助，開發中）→ 暫停交由人工處理
- **視窗控制**：`focus->` / `close->` 依標題操作視窗
- **設定外部化**：執行時自動產生 `config.json`，可調整逾時秒數與輪詢間隔，不需重新編譯
- **安全機制**：ESC 強制停止、Space 暫停/繼續、記憶體監控（超過閾值自動終止）

## 安裝與使用

1. 需安裝 [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)
2. 為每款遊戲建立一個資料夾，放入 `commands.txt` 與對應的按鈕截圖 `.png`
3. 執行 UI，選擇遊戲資料夾與指令，開始執行

## commands.txt 指令語法

### 流程控制符號

| 符號 | 說明 |
|---|---|
| `?` | 找不到圖片時縮短等待時間並跳過該步驟 |
| `↑` | 找不到圖片時縮短等待時間並重試上一步 |
| `✓` | 點擊後確認圖片消失才算完成 |
| `*n` | 該步驟重複 n 次 |
| `condition-value->order` | 條件式分支（見下方） |
| `\|` | 同時偵測多張圖片，任一命中即觸發 |
| `#n` | 同畫面有多個相符圖片時，指定第 n 個（負數代表倒數） |
| `%scale` | 指定圖片縮放比例做比對 |
| `@required_text` | OCR 文字比對（支援 `>` `<` `>=` `<=` `==` `!=` 數值比較） |

### 常用指令

| 指令 | 說明 |
|---|---|
| `waitImg->圖片名` | 無限等待圖片出現 |
| `wait數字`（如 `wait1`、`wait1.5`） | 等待指定秒數 |
| `wait_HH:MM` | 等待到指定時間點（搶票用） |
| `waitPress->按鍵` | 等待鍵盤輸入 |
| `waitClick` | 等待滑鼠左鍵點擊 |
| `move->圖片名` | 移動滑鼠到圖片位置但不點擊 |
| `mouseClick` / `rightClick` | 滑鼠左/右鍵點擊 |
| `mouseMove(x_y)` | 相對移動滑鼠 |
| `scrollUp` / `scrollDown` | 滾輪滾動 |
| `press->按鍵` | 按下單一鍵盤按鍵 |
| `"文字"` | 貼上文字（透過剪貼簿） |
| `@圖片->驗證碼圖片#位數` | 辨識驗證碼並輸入 |
| `http://網址` | 開啟瀏覽器網址 |
| `.lnk` / `.exe` / 其他關鍵字 | 啟動捷徑或應用程式 |
| `focus->視窗標題` / `close->視窗標題` / `minimize->視窗標題` | 視窗控制 |
| `match->圖片名稱` | 視窗校正，持續輸出比對信心分數 |
| `callCommand:指令名` | 呼叫另一指令 |
| `nextCommand` | 跳到下一步驟（略過當前） |
| `exitCommand` | 結束整個指令 |
| `:模組名$arg1$arg2` | 呼叫模組並帶入參數（`$1`、`$2` 於模組內取用） |

### 條件分支

```
week-Sun->free        # 今天若是星期日才執行 free
!week-Sun->free       # 今天若不是星期日才執行 free
date-15->doTask        # 每月15號才執行
img-hpBar@100->指令     # 找到 hpBar 圖片且 OCR 文字符合 "100" 才執行
img-hpBar@>50->指令     # OCR 數值比較，血量大於 50 才執行
```

### 範例

```
daily:{quest,wait1,subQuest,wait1,evolveQuest,wait1,evolve2@II,confirm,wait1,auto,wait1,skip#2,max,wait1,ok,toQuest}
```

## Socket API（給外部程式遠端呼叫）

UI 端開放 `127.0.0.1:5200`，可傳送 JSON 觸發指令執行：

```python
import socket, json

data = {"folder": "game_folder", "command": "daily"}
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect(("127.0.0.1", 5200))
client.sendall(json.dumps(data).encode("utf-8"))
client.close()
```

關閉 Core（乾淨結束多執行緒）：

```python
data = {"command": "closeCore"}
```

## 開發中 / 規劃中

- **Gemini Vision AI 逾時救援**：逾時後截圖丟給 `gemini-1.5-flash` 判斷座標，經使用者確認後可回寫進 commands.txt，實現「腳本自我修復」
- **Selenium 網頁自動化**（`webClick->`）：登入用完整載入 + 搶票瞬間用阻擋資源模式，兼顧速度與反偵測
- **Expand 預覽模式**：讓使用者在執行前看到 `expand_steps` 展開後的完整流程
- **結構化失敗紀錄**：記錄最後失敗步驟、原因與截圖快照

## 技術棧

`cv2` `numpy` `pyautogui` `pytesseract` `customtkinter` `pywin32` `keyboard` `mouse` `psutil` `pyperclip`，以 PyInstaller 打包為單一 exe。

## 免責聲明

本專案僅供教育與個人用途，使用者需自行承擔風險，作者不對任何帳號封禁負責。

## 授權

Apache License 2.0
