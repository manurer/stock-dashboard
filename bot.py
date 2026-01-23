import os
import requests
import pandas as pd
import pandas_ta as ta
import datetime
import urllib3
import json
import time

# 嘗試匯入 streamlit 來讀取 secrets，如果沒安裝也不會報錯 (為了相容性)
try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False

# 忽略 SSL 警告 (配合公司網路環境)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 1. 金鑰讀取函式 (雙模組：Secrets 優先，環境變數備用) ---
def get_secret(key_name):
    # 模式 A: 優先嘗試從 secrets.toml 讀取 (本機執行用)
    if HAS_STREAMLIT and key_name in st.secrets:
        return st.secrets[key_name]
    
    # 模式 B: 從環境變數讀取 (GitHub Actions 用)
    return os.environ.get(key_name)

# 讀取所有需要的金鑰
FUGLE_API_KEY = get_secret("FUGLE_API_KEY")
CHANNEL_ACCESS_TOKEN = get_secret("LINE_CHANNEL_ACCESS_TOKEN")
USER_ID = get_secret("LINE_USER_ID")

# 檢查金鑰是否齊全
if not FUGLE_API_KEY or not CHANNEL_ACCESS_TOKEN or not USER_ID:
    print("❌ 錯誤：找不到 API Key 或 LINE 設定。")
    print("請確認 secrets.toml 或 環境變數已正確設定。")
    exit()

# 你的關注清單
WATCHLIST = ["2330", "2408", "2454", "1519", "2603"] 

# --- 2. LINE Messaging API 發送函式 (新版) ---
def send_line_message(msg):
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {CHANNEL_ACCESS_TOKEN}'
    }
    
    payload = {
        'to': USER_ID,
        'messages': [
            {
                'type': 'text',
                'text': msg
            }
        ]
    }

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        if response.status_code == 200:
            print("✅ LINE 通知發送成功！")
        else:
            print(f"❌ 發送失敗: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"❌ 發生錯誤: {e}")

# --- 3. 抓取歷史資料 ---
def get_historical_data(symbol_id):
    try:
        today = datetime.date.today().isoformat()
        # 抓 300 天 (符合 Fugle 免費限制 < 1年)
        start_date = (datetime.date.today() - datetime.timedelta(days=300)).isoformat()
        
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/{symbol_id}?from={start_date}&to={today}&fields=open,high,low,close,volume"
        headers = { "X-API-KEY": FUGLE_API_KEY }
        
        # verify=False 是為了適應公司防火牆，在 GitHub 上跑其實可以拿掉，但留著無妨
        res = requests.get(url, headers=headers, verify=False)
        data = res.json()
        
        if "data" not in data or not data["data"]:
            return None
            
        df = pd.DataFrame(data["data"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        cols = ["open", "high", "low", "close", "volume"]
        df[cols] = df[cols].astype(float)
        df.rename(columns={c: c.capitalize() for c in cols}, inplace=True)
        return df
    except Exception as e:
        print(f"Error getting data for {symbol_id}: {e}")
        return None

# --- 4. 策略分析邏輯 ---
def analyze_stock(symbol, df):
    # 計算指標
    df['MA20'] = ta.sma(df['Close'], length=20)
    df['Donchian_High'] = df['High'].rolling(window=20).max().shift(1)
    df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
    
    if len(df) < 2: return []

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    signals = []
    
    # 策略 1: 唐奇安通道突破 (強力買進訊號)
    if pd.notna(curr.get('Donchian_High')):
        if curr['Close'] > curr['Donchian_High'] and prev['Close'] <= prev['Donchian_High']:
            stop_loss = curr['Close'] - (2 * curr['ATR'])
            signals.append(f"🔥 **突破箱型 (20日新高)**\n   收盤: {curr['Close']}\n   建議停損: {stop_loss:.1f}")

    # 策略 2: 均線剛站上 (趨勢轉強)
    if pd.notna(curr.get('MA20')):
        if curr['Close'] > curr['MA20'] and prev['Close'] <= prev['MA20']:
            signals.append(f"✅ **站上月線 (趨勢翻多)**\n   收盤: {curr['Close']}")

    return signals

# --- 5. 主程式 ---
if __name__ == "__main__":
    print("🚀 開始執行 AI 股市掃描 (Messaging API 版)...")
    message_buffer = []

    for symbol in WATCHLIST:
        print(f"正在分析 {symbol}...")
        # 避免 API 呼叫太快被鎖，稍微休息一下
        time.sleep(1.0) 
        
        df = get_historical_data(symbol)
        if df is not None:
            signals = analyze_stock(symbol, df)
            if signals:
                signal_txt = "\n".join(signals)
                message_buffer.append(f"【{symbol} 訊號觸發】\n{signal_txt}")
    
    # 整合發送 (Messaging API 一次可以傳很長，但為了閱讀體驗，我們整合在一起發)
    if message_buffer:
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        final_msg = f"📊 AI 戰情室日報 ({today_str})\n" + "\n--------------------\n".join(message_buffer)
        
        # 發送 LINE
        send_line_message(final_msg)
    else:
        print("💤 今日無特殊訊號，不發送通知。")