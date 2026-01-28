import pandas as pd
import pandas_ta as ta
import numpy as np
from FinMind.data import DataLoader 
import requests
import urllib3
import functools
import datetime

# --- 🔥 核彈級防火牆破解 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
original_request = requests.Session.request
def patched_request(self, method, url, *args, **kwargs):
    kwargs['verify'] = False
    return original_request(self, method, url, *args, **kwargs)
requests.Session.request = patched_request

# --- 🔥 真實籌碼與基本面資料抓取 (v10.1) ---
def get_real_chip_data(df, symbol):
    try:
        dl = DataLoader()
        start_date = df.index[0].strftime('%Y-%m-%d')
        
        # 1. 三大法人 & 融資融券
        chip_data = dl.taiwan_stock_institutional_investors(stock_id=symbol, start_date=start_date)
        margin_data = dl.taiwan_stock_margin_purchase_short_sale(stock_id=symbol, start_date=start_date)
        
        # 2. 抓取月營收 (範圍拉長以確保能計算 YoY)
        rev_start_date = (df.index[0] - pd.Timedelta(days=400)).strftime('%Y-%m-%d')
        revenue_data = dl.taiwan_stock_month_revenue(stock_id=symbol, start_date=rev_start_date)

        # 處理法人
        if chip_data is not None and not chip_data.empty:
            chip_data['date'] = pd.to_datetime(chip_data['date'])
            chip_data['net'] = (chip_data['buy'] - chip_data['sell']) / 1000 
            pivot_df = chip_data.pivot(index='date', columns='name', values='net').fillna(0)
            
            trust_net = pivot_df.get('Investment_Trust', pd.Series(0, index=pivot_df.index))
            foreign_net = pivot_df.get('Foreign_Investor', pd.Series(0, index=pivot_df.index)) 
            
            df['Trust_Net'] = trust_net.reindex(df.index).fillna(0.0)
            df['Foreign_Net'] = foreign_net.reindex(df.index).fillna(0.0)
            df['Trust_Cum'] = df['Trust_Net'].cumsum()
            df['Foreign_Cum'] = df['Foreign_Net'].cumsum()
        else:
            df['Trust_Net'] = 0.0
            df['Foreign_Net'] = 0.0
            df['Trust_Cum'] = 0.0
            df['Foreign_Cum'] = 0.0

        # 處理融資 & 限額
        if margin_data is not None and not margin_data.empty:
            margin_data['date'] = pd.to_datetime(margin_data['date'])
            margin_data['Margin_Balance'] = margin_data['MarginPurchaseTodayBalance'] / 1000
            
            if 'MarginPurchaseLimit' in margin_data.columns:
                margin_data['Margin_Limit'] = margin_data['MarginPurchaseLimit'] / 1000
            else:
                margin_data['Margin_Limit'] = 0.0
            
            m_bal = margin_data.set_index('date')['Margin_Balance']
            m_lim = margin_data.set_index('date')['Margin_Limit']
            
            df['Margin_Balance'] = m_bal.reindex(df.index).ffill()
            df['Margin_Limit'] = m_lim.reindex(df.index).ffill()
        else:
            df['Margin_Balance'] = 0.0
            df['Margin_Limit'] = 0.0

        # 處理營收 (自動計算 YoY)
        if revenue_data is not None and not revenue_data.empty:
            revenue_data['date'] = pd.to_datetime(revenue_data['date'])
            revenue_data = revenue_data.sort_values('date')
            
            if 'revenue_year_growth_rate' not in revenue_data.columns:
                revenue_data['revenue'] = pd.to_numeric(revenue_data['revenue'], errors='coerce')
                revenue_data['revenue_year_growth_rate'] = revenue_data['revenue'].pct_change(periods=12) * 100
            
            rev_series = revenue_data.set_index('date')['revenue_year_growth_rate']
            df['Revenue_YoY'] = rev_series.reindex(df.index, method='ffill')
        else:
            df['Revenue_YoY'] = np.nan

        return df

    except Exception as e:
        print(f"❌ FinMind 資料抓取失敗 {symbol}: {e}")
        df['Trust_Net'] = 0.0
        df['Foreign_Net'] = 0.0
        df['Margin_Balance'] = 0.0
        df['Margin_Limit'] = 0.0
        df['Revenue_YoY'] = np.nan
        return df

# 1. 計算技術指標
def calculate_indicators(df, symbol=None):
    df = df.copy()
    if symbol: df = get_real_chip_data(df, symbol)
    else:
        df['Trust_Net'] = 0.0
        df['Foreign_Net'] = 0.0
        df['Margin_Balance'] = 0.0
        df['Margin_Limit'] = 0.0
        df['Revenue_YoY'] = np.nan
    
    # 基礎指標
    df['MA5'] = ta.sma(df['Close'], length=5)
    df['MA10'] = ta.sma(df['Close'], length=10)
    df['MA20'] = ta.sma(df['Close'], length=20)
    if len(df) >= 60:
        df['MA60'] = ta.sma(df['Close'], length=60)
    else: df['MA60'] = None
    df['Vol_MA5'] = ta.sma(df['Volume'], length=5)
    df['RSI'] = ta.rsi(df['Close'], length=14)
    stoch = ta.stoch(df['High'], df['Low'], df['Close'], k=9, d=3, smooth_k=3)
    if stoch is not None:
        df['K'] = stoch[stoch.columns[0]]
        df['D'] = stoch[stoch.columns[1]]
    macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
    if macd is not None: df['MACD_Hist'] = macd[macd.columns[1]]
    bbands = ta.bbands(df['Close'], length=20, std=2)
    if bbands is not None:
        df['BB_Upper'] = bbands[bbands.columns[0]]
        df['BB_Lower'] = bbands[bbands.columns[2]]
    if 'MA20' in df.columns:
        df['BIAS_20'] = ((df['Close'] - df['MA20']) / df['MA20']) * 100
    df['Donchian_High'] = df['High'].rolling(window=20).max().shift(1)
    df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
    df['OBV'] = ta.obv(df['Close'], df['Volume'])
    df['OBV_MA20'] = ta.sma(df['OBV'], length=20)
    adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=14)
    if adx_df is not None: df['ADX'] = adx_df[adx_df.columns[0]]

    # 融資使用率
    df['Margin_Util_Rate'] = 0.0
    mask = df['Margin_Limit'] > 0
    df.loc[mask, 'Margin_Util_Rate'] = (df.loc[mask, 'Margin_Balance'] / df.loc[mask, 'Margin_Limit']) * 100

    # 位階 (Position Rank)
    window_days = 250
    df['High_250'] = df['High'].rolling(window=window_days, min_periods=60).max()
    df['Low_250'] = df['Low'].rolling(window=window_days, min_periods=60).min()
    
    df['Price_Position'] = 50.0 
    denom = df['High_250'] - df['Low_250']
    valid_mask = denom > 0
    df.loc[valid_mask, 'Price_Position'] = ((df['Close'] - df['Low_250']) / denom) * 100

    return df

# 2. 策略邏輯與評分 (v10.1 波段抄底特化版)
def analyze_strategy(df, timeframe_label="日線"):
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3]
    score = 0
    report_list = []
    score_details = []
    short_signals = []
    ma_term = "月線" if timeframe_label == "日線" else "20MA"

    # --- 0. 基本面濾網 ---
    rev_yoy = curr.get('Revenue_YoY', np.nan)
    if pd.notna(rev_yoy):
        if rev_yoy > 20:
            report_list.append(f"📊 **營收高成長 (YoY {rev_yoy:.1f}%)**：基本面強勁。")
            score += 1
            score_details.append(("營收成長", "+1"))
        elif rev_yoy < -20:
            report_list.append(f"⚠️ **營收衰退 (YoY {rev_yoy:.1f}%)**：基本面疲弱。")
            score -= 1 
            score_details.append(("營收衰退", "-1"))

    # --- 0. 位階判斷 ---
    pos = curr.get('Price_Position', 50)
    is_low_position = pos < 20
    is_high_position = pos > 85

    if is_low_position:
        report_list.append(f"💎 **低位階 (PR {pos:.0f}%)**：處於近一年低檔區，具反彈潛力。")
    elif is_high_position:
        report_list.append(f"🏔️ **高位階 (PR {pos:.0f}%)**：處於近一年高檔區，留意追高風險。")

    # --- 1. 趨勢 ---
    if pd.notna(curr.get('MA20')):
        if curr['Close'] > curr['MA20']:
            report_list.append(f"✅ **趨勢偏多**：站上{ma_term}。")
            score += 2
            score_details.append((f"站上{ma_term}", "+2"))
            if prev['Close'] <= prev['MA20']: short_signals.append(f"✅ 站上{ma_term}")
        else:
            report_list.append(f"🔻 **趨勢偏空**：跌破{ma_term}。")
            score -= 2
            score_details.append((f"跌破{ma_term}", "-2"))
        
        if prev.get('MA20') and curr['MA20'] < prev['MA20']:
             report_list.append(f"📉 **{ma_term}下彎**：壓力沉重。")
             score -= 1
             score_details.append((f"{ma_term}下彎", "-1"))

    if pd.notna(curr.get('MA5')) and pd.notna(curr.get('MA20')):
        if curr['MA5'] > curr['MA20'] and prev['MA5'] <= prev['MA20']:
            if is_low_position:
                report_list.append(f"✨ **低檔金叉**：位階低且均線翻多，黃金買點！")
                score += 4 
                score_details.append(("低檔金叉", "+4"))
                short_signals.append("✨ 低檔金叉")
            else:
                report_list.append(f"✨ **均線金叉**：5MA 穿過 {ma_term}。")
                score += 3
                score_details.append(("均線金叉", "+3"))
                short_signals.append("✨ 均線金叉")

    if pd.notna(curr.get('MA60')):
        if curr['Close'] < curr['MA60']:
            if is_low_position:
                 report_list.append("💔 **跌破季線(低位階)**：處於低檔整理。")
                 score -= 1 
                 score_details.append(("跌破季線", "-1"))
            else:
                report_list.append("💔 **跌破生命線(60MA)**：中長線空。")
                score -= 3
                score_details.append(("跌破季線", "-3"))
            
        if pd.notna(curr.get('MA5')) and pd.notna(curr.get('MA20')):
            if curr['MA5'] < curr['MA20'] and curr['MA20'] < curr['MA60']:
                report_list.append("💀 **空頭排列**：均線蓋頭反壓。")
                score -= 3 
                score_details.append(("空頭排列", "-3"))

    # --- 2. 型態 ---
    if pd.notna(curr.get('Vol_MA5')):
        pct = (curr['Close'] - prev['Close']) / prev['Close'] * 100
        if pct < -3 and curr['Volume'] > (curr['Vol_MA5'] * 2):
            report_list.append("💀 **爆量長黑**：主力恐慌出貨。")
            score -= 4 
            score_details.append(("爆量長黑", "-4"))

    if prev['Close'] > prev['Open'] and curr['Close'] < curr['Open']:
        if curr['Open'] >= prev['Close'] and curr['Close'] <= prev['Open']:
            report_list.append("🕯️ **空頭吞噬**：反轉型態。")
            score -= 2
            score_details.append(("空頭吞噬", "-2"))

    # --- 3. 動能 ---
    if pd.notna(curr.get('K')):
        is_bearish = False
        if pd.notna(curr.get('MA60')) and curr['MA20'] < curr['MA60']: is_bearish = True
        
        if curr['K'] > curr['D'] and prev['K'] <= prev['D'] and curr['K'] < 50:
            if is_bearish and not is_low_position:
                report_list.append("🏹 **KD 低檔金叉(弱)**：空頭反彈。")
                score += 1 
            else:
                report_list.append("🏹 **KD 低檔金叉**：反彈訊號。")
                score += 2
                score_details.append(("KD金叉", "+2"))
        elif curr['K'] < curr['D'] and prev['K'] >= prev['D'] and curr['K'] > 80:
            report_list.append("⚠️ **KD 高檔死叉**：修正訊號。")
            score -= 2
            score_details.append(("KD死叉", "-2"))

    if pd.notna(curr.get('MACD_Hist')):
        if curr['MACD_Hist'] > 0 and prev['MACD_Hist'] <= 0:
            report_list.append("🐂 **MACD 翻紅**：動能轉強。")
            score += 2
            score_details.append(("MACD翻紅", "+2"))

    # --- 4. 突破 ---
    if pd.notna(curr.get('Donchian_High')) and curr['Close'] > curr['Donchian_High'] and prev['Close'] <= prev['Donchian_High']:
        if is_high_position:
             report_list.append("🔥 **唐奇安突破(高檔)**：創20K新高，留意追高風險。")
             score += 2 
             score_details.append(("唐奇安突破", "+2"))
        else:
            report_list.append("🔥 **唐奇安突破**：底部發動，創20K新高！")
            score += 3
            score_details.append(("唐奇安突破", "+3"))
            short_signals.append("🔥 創新高")
            
    if pd.notna(curr.get('BB_Upper')) and curr['Close'] >= curr['BB_Upper']:
        report_list.append("🚀 **布林突破**：強勢格局。")
        score += 2
        score_details.append(("布林突破", "+2"))

    # --- 5. 籌碼 ---
    has_data = curr.get('Trust_Net', 0) != 0
    t_1 = curr.get('Trust_Net', 0)
    t_2 = prev.get('Trust_Net', 0)
    t_3 = prev2.get('Trust_Net', 0)
    
    # (A) 土洋對作
    f_1 = curr.get('Foreign_Net', 0)
    m_inc = curr.get('Margin_Balance', 0) - prev.get('Margin_Balance', 0)
    if f_1 < -1000 and m_inc > 500:
        report_list.append(f"⚔️ **土洋對作**：外資賣{int(abs(f_1))}張，融資增{int(m_inc)}張。")
        score -= 3 
        score_details.append(("籌碼對立", "-3"))
    
    # (B) 融資過熱
    m_rate = curr.get('Margin_Util_Rate', 0)
    if m_rate > 40:
        if m_rate > 60:
            report_list.append(f"🧨 **融資爆表({m_rate:.1f}%)**：籌碼極度凌亂。")
            score -= 3
            score_details.append(("融資爆表", "-3"))
        else:
            report_list.append(f"⚠️ **融資過熱({m_rate:.1f}%)**：籌碼擁擠。")
            score -= 1
            score_details.append(("融資警戒", "-1"))
    elif m_rate > 0:
        pass

    # (C) 投信邏輯
    is_below_ma20 = (curr['Close'] < curr['MA20']) if pd.notna(curr.get('MA20')) else False
    if t_1 > 0 and t_2 > 0 and t_3 > 0:
        if curr.get('BIAS_20', 0) > 15:
            report_list.append(f"⚠️ **投信連買**：但乖離過大。")
            score += 1
        elif is_below_ma20:
            if is_low_position:
                 report_list.append(f"🛡️ **投信低檔建倉**：位階低且投信連買，潛力大。")
                 score += 2 
                 score_details.append(("投信建倉", "+2"))
            else:
                report_list.append(f"🛡️ **投信低檔護盤**：股價破月線，視為防守。")
                score += 1 
                score_details.append(("投信護盤", "+1"))
        else:
            report_list.append(f"🔥 **投信連三買**：波段確立！")
            score += 3
            score_details.append((f"投信連買", "+3"))
            short_signals.append(f"🔥 投信連三買")
    elif has_data and t_1 > 0 and t_2 <= 0:
        is_breakout = (curr['Close'] > curr.get('Donchian_High', 99999))
        if is_breakout:
            report_list.append(f"🚀 **投信點火**：首日買進且突破。")
            score += 3
            score_details.append(("投信起漲", "+3"))
            short_signals.append("🚀 投信起漲")
        else:
            report_list.append(f"🏦 **投信試單**：買進 {int(t_1)} 張。")
            score += 1
            score_details.append(("投信試單", "+1"))
    elif not has_data and t_1 > 0:
         report_list.append(f"⏳ **投信趨勢偏多**：昨日買超。")
         score += 1
         score_details.append(("投信延續", "+1"))
    elif t_1 < 0:
        if t_1 < -500: 
            report_list.append(f"💀 **投信大砍**：賣 {int(abs(t_1))} 張。")
            score -= 3
            score_details.append((f"投信大賣", "-3"))
        else:
            report_list.append(f"💸 **投信調節**：賣出小量。")
            score -= 1
            score_details.append((f"投信調節", "-1"))
    else:
        if t_1 == 0:
            report_list.append("💤 **投信觀望**：今日無明顯買賣超。")

    # (D) 散戶接刀
    if is_below_ma20 and m_inc > 0:
        report_list.append(f"☠️ **散戶接刀**：股價弱勢且融資增加。")
        score -= 3 
        score_details.append(("散戶接刀", "-3"))

    # --- 6. 風險 ---
    if pd.notna(curr.get('OBV')) and pd.notna(curr.get('OBV_MA20')) and curr['OBV'] > curr['OBV_MA20']:
        report_list.append("💰 **量能健康**。")
        score += 1
        score_details.append(("OBV偏多", "+1"))

    is_strong = False
    if pd.notna(curr.get('ADX')):
        if curr['ADX'] < 20:
            report_list.append("🐌 **盤整泥沼**。")
            score = max(0, score - 2) 
            score_details.append(("盤整修正", "-2"))
        elif curr['ADX'] > 30: 
            is_strong = True
            if curr['ADX'] > prev['ADX']:
                report_list.append("🚄 **趨勢加速**。")
                score += 1
                score_details.append(("ADX加速", "+1"))

    if pd.notna(curr.get('BIAS_20')):
        bias = curr['BIAS_20']
        if bias > 18: 
            report_list.append(f"⚠️ **乖離過大({bias:.1f}%)**。")
            score -= 3
            score_details.append(("乖離極大", "-3"))
        elif bias > 12:
            if is_strong: report_list.append(f"🔥 **強勢乖離**：暫不扣分。")
            else:
                report_list.append(f"⚠️ **乖離偏高**。")
                score -= 2
                score_details.append(("乖離過大", "-2"))
        elif bias > 8:
            if not is_strong:
                report_list.append(f"⚠️ **乖離警戒**。")
                score -= 1
                score_details.append(("乖離警戒", "-1"))
        elif bias < -12:
            report_list.append("💎 **負乖離過大**。")
            score += 1
            score_details.append(("負乖離", "+1"))
        else:
            pass

    stop_loss = curr['Close'] - (2 * curr['ATR']) if pd.notna(curr.get('ATR')) else None
    if stop_loss: report_list.append(f"🛡️ **ATR 停損**：{stop_loss:.2f}")

    if score >= 6: decision, color = "強力買進", "#FF0000"
    elif score >= 2: decision, color = "偏多操作", "#FFA500"
    elif score <= -3: decision, color = "建議賣出", "#008000"
    else: decision, color = "觀望整理", "#808080"

    return {
        "score": score, "decision": decision, "color": color,
        "report_list": report_list, "score_details": score_details,
        "stop_loss": stop_loss, "short_signals": short_signals
    }

# --- 回測 (v10.2: 提高門檻版) ---
def run_backtest(df, days_to_test=60, threshold=5):
    """
    threshold=4 : 只統計 AI總分 >= 4 的高品質交易
    這樣能過濾掉只是「稍微站上月線(2分)」的弱勢訊號
    """
    backtest_logs = []
    if len(df) < days_to_test + 22: return []
    for i in range(len(df) - days_to_test, len(df) - 1):
        current_slice = df.iloc[:i+1]
        res = analyze_strategy(current_slice)
        
        # 🔥 關鍵修改：門檻從 2 提高到 threshold (預設 4)
        if res['score'] >= threshold:
            if i + 1 >= len(df): continue
            buy_p = df.iloc[i+1]['Open']
            buy_d = df.index[i+1]
            r5 = ((df.iloc[i+6]['Close'] - buy_p)/buy_p*100) if i+6 < len(df) else None
            r10 = ((df.iloc[i+11]['Close'] - buy_p)/buy_p*100) if i+11 < len(df) else None
            r20 = ((df.iloc[i+21]['Close'] - buy_p)/buy_p*100) if i+21 < len(df) else None
            backtest_logs.append({
                "訊號日期": current_slice.index[-1].strftime('%Y-%m-%d'),
                "買進日期": buy_d.strftime('%Y-%m-%d'), "買入成本": buy_p,
                "AI總分": res['score'], "訊號": res['decision'],
                "後5日漲幅": r5, "後10日漲幅": r10, "後20日漲幅": r20
            })
    return backtest_logs