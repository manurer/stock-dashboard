import pandas as pd
import pandas_ta as ta

# 1. 計算技術指標
def calculate_indicators(df):
    df = df.copy()
    
    # --- A. 基礎指標 ---
    df['MA5'] = ta.sma(df['Close'], length=5)
    df['MA10'] = ta.sma(df['Close'], length=10)
    df['MA20'] = ta.sma(df['Close'], length=20)
    if len(df) >= 60:
        df['MA60'] = ta.sma(df['Close'], length=60)
    else:
        df['MA60'] = None

    df['RSI'] = ta.rsi(df['Close'], length=14)
    
    stoch = ta.stoch(df['High'], df['Low'], df['Close'], k=9, d=3, smooth_k=3)
    if stoch is not None:
        k_col = [c for c in stoch.columns if c.startswith('STOCHk')][0]
        d_col = [c for c in stoch.columns if c.startswith('STOCHd')][0]
        df['K'] = stoch[k_col]
        df['D'] = stoch[d_col]

    macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
    if macd is not None:
        hist_col = [c for c in macd.columns if c.startswith('MACDh')][0]
        df['MACD_Hist'] = macd[hist_col]

    bbands = ta.bbands(df['Close'], length=20, std=2)
    if bbands is not None:
        upper_col = [c for c in bbands.columns if c.startswith('BBU')][0]
        lower_col = [c for c in bbands.columns if c.startswith('BBL')][0]
        df['BB_Upper'] = bbands[upper_col]
        df['BB_Lower'] = bbands[lower_col]

    # --- B. 波段指標 ---
    if 'MA20' in df.columns:
        df['BIAS_20'] = ((df['Close'] - df['MA20']) / df['MA20']) * 100
    
    df['Donchian_High'] = df['High'].rolling(window=20).max().shift(1)
    df['Donchian_Low'] = df['Low'].rolling(window=20).min().shift(1)
    df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)

    # --- 🔥 C. 新增指標：OBV (能量潮) ---
    df['OBV'] = ta.obv(df['Close'], df['Volume'])
    # 計算 OBV 的 20日均線，用來判斷量能趨勢
    df['OBV_MA20'] = ta.sma(df['OBV'], length=20)

    # --- 🔥 D. 新增指標：ADX (趨勢強度) ---
    # ADX 需要 High, Low, Close
    adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=14)
    if adx_df is not None:
        # pandas_ta 的 adx 回傳欄位通常是 ADX_14, DMP_14, DMN_14
        adx_col = [c for c in adx_df.columns if c.startswith('ADX')][0]
        df['ADX'] = adx_df[adx_col]

    # --- 🔥 E. 新增指標：量價異常 (Volume Anomaly) ---
    # 計算 5日均量
    df['Vol_MA5'] = ta.sma(df['Volume'], length=5)

    return df

# 2. 策略邏輯與評分
def analyze_strategy(df, timeframe_label="日線"):
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    score = 0
    report_list = []
    score_details = []
    short_signals = []
    
    ma_term = "月線" if timeframe_label == "日線" else "20MA"

    # --- 1. 趨勢 (均線) ---
    if pd.notna(curr.get('MA20')):
        if curr['Close'] > curr['MA20']:
            report_list.append(f"✅ **趨勢偏多**：股價站上 {ma_term}。")
            score += 2
            score_details.append((f"站上{ma_term}", "+2"))
            if prev['Close'] <= prev['MA20']: short_signals.append(f"✅ 剛站上{ma_term}")
        else:
            report_list.append(f"🔻 **趨勢偏空**：股價跌破 {ma_term}。")
            score -= 2
            score_details.append((f"跌破{ma_term}", "-2"))

    if pd.notna(curr.get('MA5')) and pd.notna(curr.get('MA20')):
        if curr['MA5'] > curr['MA20'] and prev['MA5'] <= prev['MA20']:
            report_list.append(f"✨ **均線金叉**：5MA 穿過 {ma_term}。")
            score += 3
            score_details.append(("均線金叉", "+3"))
            short_signals.append("✨ 均線黃金交叉")

    # --- 2. 動能 (KD / MACD) ---
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

    # --- 3. 波段與突破 ---
    if pd.notna(curr.get('Donchian_High')):
        if curr['Close'] > curr['Donchian_High'] and prev['Close'] <= prev['Donchian_High']:
            report_list.append("🔥 **唐奇安突破**：創20K新高，波段發動！")
            score += 3
            score_details.append(("唐奇安突破", "+3"))
            short_signals.append("🔥 突破箱型 (新高)")

    if pd.notna(curr.get('BB_Upper')):
        if curr['Close'] >= curr['BB_Upper']:
            report_list.append("🚀 **布林突破**：沿上軌噴出，強勢格局。")
            score += 2
            score_details.append(("布林突破", "+2"))

    # --- 4. 籌碼與量能 (新功能) ---
    # OBV 趨勢判斷
    if pd.notna(curr.get('OBV')) and pd.notna(curr.get('OBV_MA20')):
        if curr['OBV'] > curr['OBV_MA20']:
            # 只有當 OBV 創新高時才加分，這裡簡化為站上均線
            report_list.append("💰 **量能健康 (OBV)**：買盤資金持續進駐。")
            score += 1
            score_details.append(("OBV偏多", "+1"))
        else:
            report_list.append("💸 **量能退潮 (OBV)**：資金流出中。")
            score -= 1
            score_details.append(("OBV偏空", "-1"))

    # 量價背離檢查 (上漲但量縮)
    if pd.notna(curr.get('Vol_MA5')):
        if curr['Close'] > prev['Close'] and curr['Volume'] < curr['Vol_MA5'] * 0.8:
            report_list.append("⚠️ **量價背離**：價漲量縮，追價買盤不足。")
            score -= 1 # 稍微扣分警告
            score_details.append(("量價背離", "-1"))

    # --- 5. 趨勢強度濾網 (ADX) ---
    if pd.notna(curr.get('ADX')):
        if curr['ADX'] < 20:
            report_list.append("🐌 **盤整泥沼 (ADX<20)**：無明顯趨勢，均線訊號易失效。")
            # 盤整時，扣除部分趨勢分數，避免假訊號
            score = max(0, score - 2) 
            score_details.append(("盤整修正", "-2"))
        elif curr['ADX'] > 25 and curr['ADX'] > prev['ADX']:
            report_list.append("🚄 **趨勢加速 (ADX>25)**：趨勢動能強勁。")
            score += 1
            score_details.append(("ADX加速", "+1"))

    # --- 6. 風險控管 ---
    if pd.notna(curr.get('BIAS_20')):
        if curr['BIAS_20'] > 15:
            report_list.append("⚠️ **乖離過大**：短線過熱，風險高。")
            score -= 2
            score_details.append(("乖離過大", "-2"))
        elif curr['BIAS_20'] < -12:
            report_list.append("💎 **負乖離過大**：短線超跌。")
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