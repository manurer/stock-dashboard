import os
import requests
import pandas as pd
import datetime
import urllib3
import json
import time
import stock_logic # 🔥 匯入共用邏輯

# 嘗試匯入 streamlit 來讀取 secrets
try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False

# 忽略 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 1. 金鑰讀取 ---
def get_secret(key_name):
    if HAS_STREAMLIT and key_name in st.secrets:
        return st.secrets[key_name]
    return os.environ.get(key_name)

FUGLE_API_KEY = get_secret("FUGLE_API_KEY")
CHANNEL_ACCESS_TOKEN = get_secret("LINE_CHANNEL_ACCESS_TOKEN")
USER_ID = get_secret("LINE_USER_ID")

if not FUGLE_API_KEY or not CHANNEL_ACCESS_TOKEN or not USER_ID:
    print("❌ 錯誤：找不到 API Key 或 LINE 設定。")
    print("請確認 secrets.toml 或 環境變數已正確設定。")
    exit()

# 關注清單 (可改為讀取 json)
WATCHLIST = ["2330", "2408", "2454", "1519", "2603"] 

# --- 2. LINE Messaging API ---
def send_line_message(msg):
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {CHANNEL_ACCESS_TOKEN}'
    }
    payload = {
        'to': USER_ID,
        'messages': [{'type': 'text', 'text': msg}]
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
        start_date = (datetime.date.today() - datetime.timedelta(days=300)).isoformat()
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/{symbol_id}?from={start_date}&to={today}&fields=open,high,low,close,volume"
        headers = { "X-API-KEY": FUGLE_API_KEY }
        
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

# --- 4. 機器人分析邏輯 (外包) ---
def analyze_stock_for_bot(symbol, df):
    # 1. 計算指標 (使用共用邏輯)
    df_final = stock_logic.calculate_indicators(df)
    
    # 2. 策略判斷 (使用共用邏輯)
    result = stock_logic.analyze_strategy(df_final)
    
    # 3. 取得機器人專用的簡訊
    signals = result["short_signals"]
    
    # 如果有重要訊號，加上收盤價和停損價
    if signals:
        curr = df_final.iloc[-1]
        msg = "\n".join(signals)
        msg += f"\n💰 收盤: {curr['Close']}"
        if result["stop_loss"]:
             msg += f"\n🛡️ 停損: {result['stop_loss']:.1f}"
        return msg
        
    return None

# --- 5. 主程式 ---
if __name__ == "__main__":
    print("🚀 開始執行 AI 股市掃描 (模組化版)...")
    message_buffer = []

    for symbol in WATCHLIST:
        print(f"正在分析 {symbol}...")
        time.sleep(1.0) 
        
        df = get_historical_data(symbol)
        if df is not None:
            signal_msg = analyze_stock_for_bot(symbol, df)
            
            if signal_msg:
                message_buffer.append(f"【{symbol} 訊號觸發】\n{signal_msg}")
    
    if message_buffer:
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        final_msg = f"📊 AI 戰情室日報 ({today_str})\n" + "\n--------------------\n".join(message_buffer)
        send_line_message(final_msg)
    else:
        print("💤 今日無特殊訊號。")