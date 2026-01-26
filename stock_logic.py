import pandas as pd
import pandas_ta as ta
import numpy as np
from FinMind.data import DataLoader 
import requests
import urllib3
import ssl
import os

# --- 🔥 核彈級防火牆破解 (Monkey Patch requests) ---
# 強制關閉所有 Requests 的 SSL 驗證
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
original_request = requests.Session.request
def patched_request(self, method, url, *args, **kwargs):
    kwargs['verify'] = False
    return original_request(self, method, url, *args, **kwargs)
requests.Session.request = patched_request
# -----------------------------------------------------

# --- 🔥 真實籌碼資料抓取 (使用 FinMind) ---
def get_real_chip_data(df, symbol):
    try:
        dl = DataLoader()
        # 抓取範圍：抓最近 360 天
        start_date = df.index[0].strftime('%Y-%m-%d')
        
        chip_data = dl.taiwan_stock_institutional_investors(
            stock_id=symbol,
            start_date=start_date
        )
        
        if chip_data is None or chip_data.empty:
            return df 

        # 資料整理
        chip_data['date'] = pd.to_datetime(chip_data['date'])
        chip_data['net'] = (chip_data['buy'] - chip_data['sell']) / 1000 # 換算成「張」
        
        # 樞紐分析
        pivot_df = chip_data.pivot(index='date', columns='name', values='net').fillna(0)
        
        # 準備要合併的 Series
        trust_net = pivot_df.get('Investment_Trust', pd.Series(0, index=pivot_df.index))
        foreign_net = pivot_df.get('Foreign_Investor', pd.Series(0, index=pivot_df.index))
            
        # 合併回原本的 df
        df['Trust_Net'] = trust_net.reindex(df.index).fillna(0)
        df['Foreign_Net'] = foreign_net.reindex(df.index).fillna(0)
        
        # 計算累積買賣超
        df['Trust_Cum'] = df['Trust_Net'].cumsum()
        df['Foreign_Cum'] = df['Foreign_Net'].cumsum()
        
        return df

    except Exception as e:
        print(f"❌ FinMind 資料抓取失敗 {symbol}: {e}")
        df['Trust_Net'] = 0
        df['Foreign_Net'] = 0
        df['Trust_Cum'] = 0
        df['Foreign_Cum'] = 0
        return df

# 1. 計算技術指標 (全功能版)
def calculate_indicators(df, symbol=None):
    df = df.copy()
    
    # 籌碼
    if symbol:
        df = get_real_chip_data(df, symbol)
    else:
        df['Trust_Net'] = 0
        df['Foreign_Net'] = 0
        df['Trust_Cum'] = 0
    
    # --- A. 基礎指標 ---
    df['MA5'] = ta.sma(df['Close'], length=5)
    df['MA10'] = ta.sma(df['Close'], length=10)
    df['MA20'] = ta.sma(df['Close'], length=20)
    
    # 🔥 防禦指標：季線 與 成交量均線
    if len(df) >= 60:
        df['MA60'] = ta.sma(df['Close'], length=60)
    else:
        df['MA60'] = None
        
    df['Vol_MA5'] = ta.sma(df['Volume'], length=5)

    df['RSI'] = ta.rsi(df['Close'], length=14)
    
    # KD
    stoch = ta.stoch(df['High'], df['Low'], df['Close'], k=9, d=3, smooth_k=3)
    if stoch is not None:
        # pandas_ta 的欄位名稱有時會變，這裡用通用的方式抓
        df['K'] = stoch[stoch.columns[0]]
        df['D'] = stoch[stoch.columns[1]]

    # MACD
    macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
    if macd is not None:
        # MACD Histogram 通常是第 2 個欄位
        df['MACD_Hist'] = macd[macd.columns[1]]

    # 布林通道
    bbands = ta.bbands(df['Close'], length=20, std=2)
    if bbands is not None:
        df['BB_Upper'] = bbands[bbands.columns[0]]
        df['BB_Lower'] = bbands[bbands.columns[2]]

    # --- B. 波段指標 ---
    if 'MA20' in df.columns:
        df['BIAS_20'] = ((df['Close'] - df['MA20']) / df['MA20']) * 100
    
    df['Donchian_High'] = df['High'].rolling(window=20).max().shift(1)
    df['Donchian_Low'] = df['Low'].rolling(window=20).min().shift(1)
    df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)

    # --- C. 量能與進階 ---
    df['OBV'] = ta.obv(df['Close'], df['Volume'])
    df['OBV_MA20'] = ta.sma(df['OBV'], length=20)
    
    adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=14)
    if adx_df is not None:
        df['ADX'] = adx_df[adx_df.columns[0]]

    return df

# 2. 策略邏輯與評分 (攻守兼備終極版)
def analyze_strategy(df, timeframe_label="日線"):
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3]
    
    score = 0
    report_list = []
    score_details = []
    short_signals = []
    
    ma_term = "月線" if timeframe_label == "日線" else "20MA"

    # --- 1. 趨勢與均線 (Trend) ---
    if pd.notna(curr.get('MA20')):
        if curr['Close'] > curr['MA20']:
            report_list.append(f"✅ **趨勢偏多**：股價站上 {ma_term}。")
            score += 2
            score_details.append((f"站上{ma_term}", "+2"))
            if prev['Close'] <= prev['MA20']: short_signals.append(f"✅ 站上{ma_term}")
        else:
            report_list.append(f"🔻 **趨勢偏空**：股價跌破 {ma_term}。")
            score -= 2
            score_details.append((f"跌破{ma_term}", "-2"))

    # 加分：MA5/20 金叉
    if pd.notna(curr.get('MA5')) and pd.notna(curr.get('MA20')):
        if curr['MA5'] > curr['MA20'] and prev['MA5'] <= prev['MA20']:
            report_list.append(f"✨ **均線金叉**：5MA 穿過 {ma_term}。")
            score += 3
            score_details.append(("均線金叉", "+3"))
            short_signals.append("✨ 均線金叉")

    # 🔥 扣分防禦：跌破季線 (生命線)
    if pd.notna(curr.get('MA60')):
        if curr['Close'] < curr['MA60']:
            report_list.append("💔 **跌破生命線(60MA)**：中長線趨勢轉空。")
            score -= 3
            score_details.append(("跌破季線", "-3"))

    # --- 2. 型態與K線 (Pattern) ---
    # 🔥 扣分防禦：爆量長黑
    if pd.notna(curr.get('Vol_MA5')):
        # 簡易計算漲跌幅
        pct = (curr['Close'] - prev['Close']) / prev['Close'] * 100
        # 條件：跌幅 > 3% 且 成交量 > 2倍均量
        if pct < -3 and curr['Volume'] > (curr['Vol_MA5'] * 2):
            report_list.append("💀 **爆量長黑**：主力恐慌倒貨，建議避開！")
            score -= 4 # 重扣
            score_details.append(("爆量長黑", "-4"))

    # 🔥 扣分防禦：高檔吞噬
    if prev['Close'] > prev['Open'] and curr['Close'] < curr['Open']: # 昨紅今黑
        if curr['Open'] >= prev['Close'] and curr['Close'] <= prev['Open']:
            report_list.append("🕯️ **空頭吞噬**：K線反轉型態，短線見頂。")
            score -= 2
            score_details.append(("空頭吞噬", "-2"))

    # --- 3. 動能面 (Momentum) ---
    if pd.notna(curr.get('K')):
        if curr['K'] > curr['D'] and prev['K'] <= prev['D'] and curr['K'] < 50:
            report_list.append("🏹 **KD 低檔金叉**：反彈訊號。")
            score += 2
            score_details.append(("KD金叉", "+2"))
        elif curr['K'] < curr['D'] and prev['K'] >= prev['D'] and curr['K'] > 80:
            report_list.append("⚠️ **KD 高檔死叉**：修正訊號。")
            score -= 2
            score_details.append(("KD死叉", "-2"))
            
    if pd.notna(curr.get('MACD_Hist')):
        if curr['MACD_Hist'] > 0 and prev['MACD_Hist'] <= 0:
            report_list.append("🐂 **MACD 翻紅**：主力動能轉強。")
            score += 2
            score_details.append(("MACD翻紅", "+2"))

    # --- 4. 波段與突破 (Breakout) ---
    if pd.notna(curr.get('Donchian_High')):
        if curr['Close'] > curr['Donchian_High'] and prev['Close'] <= prev['Donchian_High']:
            report_list.append("🔥 **唐奇安突破**：創20K新高，波段發動！")
            score += 3
            score_details.append(("唐奇安突破", "+3"))
            short_signals.append("🔥 創新高")

    if pd.notna(curr.get('BB_Upper')):
        if curr['Close'] >= curr['BB_Upper']:
            report_list.append("🚀 **布林突破**：沿上軌噴出，強勢格局。")
            score += 2
            score_details.append(("布林突破", "+2"))

    # --- 5. 籌碼分析 (嚴謹時間標記版) ---
    
    # 步驟 1: 判斷「今天」的籌碼出來了沒？
    has_data_today = curr.get('Trust_Net', 0) != 0
    
    # 步驟 2: 設定觀測窗口
    if has_data_today:
        # Case A: 資料已更新
        t_1 = curr.get('Trust_Net', 0)     # 今天
        t_2 = prev.get('Trust_Net', 0)     # 昨天
        t_3 = prev2.get('Trust_Net', 0)    # 前天
        time_tag = "(含今日)"
        trust_sum_5 = df['Trust_Net'].tail(5).sum()
    else:
        # Case B: 資料未更新
        t_1 = prev.get('Trust_Net', 0)     # 昨天
        t_2 = prev2.get('Trust_Net', 0)    # 前天
        t_3 = df['Trust_Net'].iloc[-4] if len(df) >= 4 else 0 # 大前天
        time_tag = "**(截至昨日)**"
        trust_sum_5 = df['Trust_Net'].iloc[-6:-1].sum()

    # 步驟 3: 策略判斷
    if t_1 > 0 and t_2 > 0 and t_3 > 0:
        if curr.get('BIAS_20', 0) > 15:
            report_list.append(f"⚠️ **投信連三買{time_tag}**：但乖離過大，留意風險。")
            score += 1
        else:
            report_list.append(f"🔥 **投信連三買{time_tag}**：籌碼鎖定，波段趨勢確立！(5日{int(trust_sum_5)}張)")
            score += 3
            score_details.append((f"投信連買", "+3"))
            short_signals.append(f"🔥 投信連買")

    elif has_data_today and t_1 > 0 and t_2 <= 0:
        is_breakout = False
        if pd.notna(curr.get('Donchian_High')) and curr['Close'] > curr['Donchian_High']: is_breakout = True
        if pd.notna(curr.get('BB_Upper')) and curr['Close'] > curr['BB_Upper']: is_breakout = True
        
        if is_breakout:
            report_list.append(f"🚀 **投信點火(今日)**：首日進場且突破關鍵價，起漲第一根！")
            score += 3
            score_details.append(("投信起漲", "+3"))
            short_signals.append("🚀 投信起漲")
        else:
            report_list.append(f"🏦 **投信試單(今日)**：首日買進 {int(t_1)} 張，觀察續航力。")
            score += 1
            score_details.append(("投信試單", "+1"))

    elif not has_data_today and t_1 > 0:
         report_list.append(f"⏳ **投信趨勢偏多**：昨日買超 {int(t_1)} 張，籌碼延續中。")
         score += 1
         score_details.append(("投信延續", "+1"))

    elif t_1 < 0:
        if t_1 < -500: 
            report_list.append(f"💀 **投信大砍{time_tag}**：大賣 {int(abs(t_1))} 張，建議避開。")
            score -= 3
            score_details.append((f"投信大賣", "-3"))
        elif t_2 < 0 and t_3 < 0:
            report_list.append(f"💸 **投信結帳{time_tag}**：連續三日調節，波段結束。")
            score -= 3
            score_details.append((f"投信連賣", "-3"))
        else:
            report_list.append(f"💸 **投信調節{time_tag}**：賣出 {int(abs(t_1))} 張。")
            score -= 1
            score_details.append((f"投信調節", "-1"))

    # --- 6. 量能與風險 (Volume & Risk) ---
    if pd.notna(curr.get('OBV')) and pd.notna(curr.get('OBV_MA20')):
        if curr['OBV'] > curr['OBV_MA20']:
            report_list.append("💰 **量能健康 (OBV)**：買盤資金持續進駐。")
            score += 1
            score_details.append(("OBV偏多", "+1"))

    if pd.notna(curr.get('ADX')):
        if curr['ADX'] < 20:
            report_list.append("🐌 **盤整泥沼 (ADX<20)**：無明顯趨勢。")
            score = max(0, score - 2) 
            score_details.append(("盤整修正", "-2"))
        elif curr['ADX'] > 25 and curr['ADX'] > prev['ADX']:
            report_list.append("🚄 **趨勢加速 (ADX>25)**：趨勢動能強勁。")
            score += 1
            score_details.append(("ADX加速", "+1"))

    if pd.notna(curr.get('BIAS_20')):
        if curr['BIAS_20'] > 15:
            report_list.append("⚠️ **乖離過大**：短線過熱，風險高。")
            score -= 2
            score_details.append(("乖離過大", "-2"))
        elif curr['BIAS_20'] < -12:
            report_list.append("💎 **負乖離過大**：短線超跌，留意反彈。")
            score += 1
            score_details.append(("負乖離", "+1"))

    stop_loss_price = None
    if pd.notna(curr.get('ATR')):
        stop_loss_price = curr['Close'] - (2 * curr['ATR'])
        report_list.append(f"🛡️ **ATR 停損**：建議設在 **{stop_loss_price:.2f}**。")

    # 總結
    if score >= 6: decision, color = "強力買進", "#FF0000"
    elif score >= 2: decision, color = "偏多操作", "#FFA500"
    elif score <= -3: decision, color = "建議賣出", "#008000"
    else: decision, color = "觀望整理", "#808080"

    return {
        "score": score,
        "decision": decision,
        "color": color,
        "report_list": report_list,
        "score_details": score_details,
        "stop_loss": stop_loss_price,
        "short_signals": short_signals
    }