import streamlit as st
import pandas as pd
import pandas_ta as ta
import datetime
import requests
import urllib3
import json
import os
import time
import plotly.graph_objects as go

# 1. --- 基礎設定 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 請在此填入您的 API KEY
try:
    API_KEY = st.secrets["FUGLE_API_KEY"]
except FileNotFoundError:
    st.error("❌ 找不到 API Key！請確認 secrets.toml 是否設定正確。")
    st.stop()

st.set_page_config(layout="wide", page_title="量化股市戰情室")

# 2. --- 狀態管理 ---
WATCHLIST_FILE = "watchlist.json"

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return ["2330", "2408", "2454", "1519"]

def save_watchlist(watchlist):
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(watchlist, f)

if 'watchlist' not in st.session_state: st.session_state.watchlist = load_watchlist()
if 'current_page' not in st.session_state: st.session_state.current_page = "📊 戰情總覽"
if 'target_stock' not in st.session_state: st.session_state.target_stock = "2408"
if 'stock_names' not in st.session_state: st.session_state.stock_names = {}

def go_to_analysis(symbol):
    st.session_state.target_stock = symbol
    st.session_state.current_page = "🔍 個股深度診斷"

# 3. --- API 功能 ---
def get_realtime_quote_full(symbol_id):
    try:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol_id}"
        headers = { "X-API-KEY": API_KEY }
        response = requests.get(url, headers=headers, verify=False)
        if response.status_code != 200: return None
        data = response.json()
        
        price = data.get("lastTrade", {}).get("price") or data.get("lastTrial", {}).get("price")
        name = data.get("name", "")
        if not name: name = symbol_id
        st.session_state.stock_names[symbol_id] = name 

        order_book = data.get("order", {})
        bids = order_book.get("bids", []) 
        asks = order_book.get("asks", []) 

        if price:
            return {
                "symbol": symbol_id, "name": name, "price": float(price),
                "change": data.get("change", 0), "change_percent": data.get("changePercent", 0),
                "prev_close": data.get("previousClose", 0),
                "bids": bids, "asks": asks
            }
        return None
    except: return None

@st.cache_data(ttl=300)
def get_historical_data(symbol_id):
    try:
        today = datetime.date.today().isoformat()
        start_date = (datetime.date.today() - datetime.timedelta(days=360)).isoformat()
        fields = "open,high,low,close,volume,turnover,change"
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/{symbol_id}?from={start_date}&to={today}&fields={fields}"
        headers = { "X-API-KEY": API_KEY }
        response = requests.get(url, headers=headers, verify=False)
        
        if response.status_code != 200: return None
        json_data = response.json()
        if "data" not in json_data or len(json_data["data"]) == 0: return None
        
        df = pd.DataFrame(json_data["data"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        cols = ["open", "high", "low", "close", "volume"]
        df[cols] = df[cols].astype(float)
        df.rename(columns={c: c.capitalize() for c in cols}, inplace=True)
        return df
    except: return None

# 4. --- 核心運算 ---

def merge_realtime_data(df, realtime_data):
    if df is None or realtime_data is None: return df
    
    df_merged = df.copy()
    last_date = df_merged.index[-1]
    today = pd.Timestamp.today().normalize()
    current_price = realtime_data['price']
    
    if last_date < today:
        new_row = pd.DataFrame({
            "Open": [current_price], "High": [current_price], 
            "Low": [current_price], "Close": [current_price], "Volume": [0]
        }, index=[today])
        df_merged = pd.concat([df_merged, new_row])
    else:
        df_merged.loc[last_date, 'Close'] = current_price
        if current_price > df_merged.loc[last_date, 'High']:
            df_merged.loc[last_date, 'High'] = current_price
        if current_price < df_merged.loc[last_date, 'Low']:
            df_merged.loc[last_date, 'Low'] = current_price
            
    return df_merged

def resample_timeframe(df, timeframe):
    if timeframe == '日線':
        return df
    
    agg_dict = {
        'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
    }
    
    try:
        if timeframe == '週線':
            df_res = df.resample('W-FRI').agg(agg_dict).dropna()
        elif timeframe == '月線':
            df_res = df.resample('M').agg(agg_dict).dropna()
        else:
            return df
        return df_res
    except:
        return df

def calculate_indicators(df):
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

    if 'MA20' in df.columns:
        df['BIAS_20'] = ((df['Close'] - df['MA20']) / df['MA20']) * 100
    
    df['Donchian_High'] = df['High'].rolling(window=20).max().shift(1)
    df['Donchian_Low'] = df['Low'].rolling(window=20).min().shift(1)
    df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)

    return df

def generate_detailed_report(df, timeframe_label="日線"):
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    score = 0
    report = []
    score_details = []
    
    ma_term = "月線" if timeframe_label == "日線" else "20MA"

    # A. 基礎趨勢
    if pd.notna(curr.get('MA20')):
        if curr['Close'] > curr['MA20']:
            report.append(f"✅ **趨勢偏多**：股價站上 {ma_term}。")
            score += 2
            score_details.append((f"站上{ma_term}", "+2"))
        else:
            report.append(f"🔻 **趨勢偏空**：股價跌破 {ma_term}。")
            score -= 2
            score_details.append((f"跌破{ma_term}", "-2"))

    if pd.notna(curr.get('MA5')) and pd.notna(curr.get('MA20')):
        if curr['MA5'] > curr['MA20'] and prev['MA5'] <= prev['MA20']:
            report.append(f"✨ **均線黃金交叉**：5MA突破 {ma_term}。")
            score += 3
            score_details.append(("均線金叉", "+3"))
    
    # B. 波段訊號
    if pd.notna(curr.get('Donchian_High')):
        if curr['Close'] > curr['Donchian_High'] and prev['Close'] <= prev['Donchian_High']:
            report.append("🔥 **突破箱型 (唐奇安)**：創20K新高。")
            score += 3
            score_details.append(("唐奇安突破", "+3"))
    
    if pd.notna(curr.get('BIAS_20')):
        if curr['BIAS_20'] > 15:
            report.append("⚠️ **乖離過大 (>15%)**：短線過熱。")
            score -= 2
            score_details.append(("乖離率過大", "-2"))
        elif curr['BIAS_20'] < -12:
            report.append("💎 **負乖離過大 (<-12%)**：短線超跌。")
            score += 1
            score_details.append(("負乖離超跌", "+1"))

    # C. 動能與震盪
    if pd.notna(curr.get('K')):
        if curr['K'] > curr['D'] and prev['K'] <= prev['D'] and curr['K'] < 50:
            report.append("🏹 **KD 低檔黃金交叉**：反彈訊號。")
            score += 2
            score_details.append(("KD低檔金叉", "+2"))
        elif curr['K'] < curr['D'] and prev['K'] >= prev['D'] and curr['K'] > 80:
            report.append("⚠️ **KD 高檔死亡交叉**：修正訊號。")
            score -= 2
            score_details.append(("KD高檔死叉", "-2"))
            
    if pd.notna(curr.get('MACD_Hist')):
        if curr['MACD_Hist'] > 0 and prev['MACD_Hist'] <= 0:
            report.append("🐂 **MACD 翻紅**：動能轉強。")
            score += 2
            score_details.append(("MACD翻紅", "+2"))
        elif curr['MACD_Hist'] < 0:
            report.append("🐻 **MACD 綠柱**：空方主導。")
            score -= 1
            score_details.append(("MACD綠柱", "-1"))

    if pd.notna(curr.get('BB_Upper')):
        if curr['Close'] >= curr['BB_Upper']:
            report.append("🚀 **布林通道突破**：沿上軌噴出。")
            score += 2
            score_details.append(("布林突破", "+2"))
    
    score_str = "**📝 詳細得分表：**\n\n"
    for item, pts in score_details:
        score_str += f"- {item}: {pts}\n"
    score_str += f"\n**🏆 總分：{score} 分**"

    # D. ATR 風控
    stop_loss_price = None
    if pd.notna(curr.get('ATR')):
        stop_loss_price = curr['Close'] - (2 * curr['ATR'])
        report.append(f"🛡️ **風控建議 (ATR)**：建議停損價 **{stop_loss_price:.2f}**。")

    if score >= 5: decision, color = "強力買進", "#FF0000"
    elif score > 0: decision, color = "偏多操作", "#FFA500"
    elif score <= -3: decision, color = "建議賣出", "#008000"
    else: decision, color = "觀望整理", "#808080"
    
    return decision, color, report, curr, score_str

# 5. --- 介面顯示區 ---

st.sidebar.title("🎛️ 戰情控制台")
page = st.sidebar.radio("選擇模式", ["📊 戰情總覽", "🔍 個股深度診斷"], key="current_page")
st.sidebar.markdown("---")
st.sidebar.subheader("📝 關注清單")

col1, col2 = st.sidebar.columns([0.7, 0.3])
new_symbol = col1.text_input("新增代號", placeholder="2408", label_visibility="collapsed")
if col2.button("➕"):
    if new_symbol and new_symbol not in st.session_state.watchlist:
        st.session_state.watchlist.append(new_symbol)
        save_watchlist(st.session_state.watchlist)
        st.rerun()
remove_symbol = st.sidebar.multiselect("移除股票", st.session_state.watchlist)
if st.sidebar.button("🗑️ 移除"):
    for s in remove_symbol: st.session_state.watchlist.remove(s)
    save_watchlist(st.session_state.watchlist)
    st.rerun()

if page == "📊 戰情總覽":
    st.title("📊 多檔股票戰情總覽")
    if not st.session_state.watchlist: st.info("清單是空的")
    else:
        if len(st.session_state.watchlist) > 8:
            st.warning("⚠️ 關注股票較多，載入分析數據可能需要一點時間...")
            
        cols = st.columns(4)
        for i, symbol in enumerate(st.session_state.watchlist):
            time.sleep(1.0) 
            with cols[i % 4]:
                real_data = get_realtime_quote_full(symbol)
                signal_text = "分析中..."
                signal_color = "#888"
                
                if real_data:
                    hist_data = get_historical_data(symbol)
                    if hist_data is not None:
                        try:
                            df_merged = merge_realtime_data(hist_data, real_data)
                            df_final = calculate_indicators(df_merged)
                            decision, color_code, _, _, _ = generate_detailed_report(df_final)
                            signal_text = decision
                            signal_color = color_code
                        except:
                            signal_text = "數據不足"
                    
                    change = real_data['change']
                    pct = real_data['change_percent']
                    price_color = "#FF0000" if change > 0 else "#008000" if change < 0 else "#666666"
                    
                    st.markdown(f"""
                    <div style="border:1px solid #ddd; padding:10px; border-radius:10px; margin-bottom:10px; background-color:#1E1E1E;">
                        <div style="font-size:16px; font-weight:bold; color:#FFF;">
                            {real_data['symbol']} {real_data['name']}
                        </div>
                        <div style="margin-top:5px; margin-bottom:5px;">
                            <span style="background-color:{signal_color}; color:white; padding:2px 8px; border-radius:4px; font-size:12px;">
                                {signal_text}
                            </span>
                        </div>
                        <div style="font-size:24px; font-weight:bold; color:{price_color};">
                            {real_data['price']}
                        </div>
                        <div style="font-size:14px; color:{price_color};">
                            {change} ({pct}%)
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    st.button(f"🔍 詳細 {real_data['name']}", key=f"btn_{symbol}", on_click=go_to_analysis, args=(symbol,))
                else: st.metric(symbol, "--", "連線失敗")

elif page == "🔍 個股深度診斷":
    st.title("🔍 個股深度診斷")
    try: idx = st.session_state.watchlist.index(st.session_state.target_stock)
    except: idx = 0
    
    col1, col2 = st.columns([1, 1])
    def fmt(s): return f"{s} {st.session_state.stock_names.get(s,'')}"
    sel = col1.selectbox("從清單選擇", st.session_state.watchlist, index=idx, format_func=fmt)
    man = col2.text_input("或輸入代號")
    target = man if man else sel
    
    if target:
        st.session_state.target_stock = target
        
        # --- 週期選擇器 ---
        timeframe = st.radio("⏳ 選擇K線週期", ["日線", "週線", "月線"], index=0, horizontal=True)
        
        with st.spinner(f'正在分析：{target} ({timeframe})...'):
            df_h = get_historical_data(target)
            real = get_realtime_quote_full(target)
            
            if df_h is not None:
                df_merged = merge_realtime_data(df_h, real)
                df_resampled = resample_timeframe(df_merged, timeframe)
                df_final = calculate_indicators(df_resampled)
                decision, color, reports, curr, score_str = generate_detailed_report(df_final, timeframe)
                
                name = real['name'] if real else target
                st.subheader(f"{target} {name} - {timeframe}戰情")
                
                main_col, order_col = st.columns([3, 1])
                
                with main_col:
                    k_col1, k_col2, k_col3, k_col4 = st.columns(4)
                    
                    change = real['change'] if real else 0
                    pct = real['change_percent'] if real else 0
                    price_color = "#FF0000" if change > 0 else "#008000" if change < 0 else "#666666"
                    
                    k_col1.markdown("**目前股價**")
                    k_col1.markdown(f"""
                        <div style="color: {price_color}; font-size: 32px; font-weight: bold; line-height: 1.2;">
                            {curr['Close']:.2f}
                        </div>
                        <div style="color: {price_color}; font-size: 16px;">
                            {change} ({pct}%)
                        </div>
                    """, unsafe_allow_html=True)

                    if pd.notna(curr.get('K')):
                        kd_color = "#FF0000" if curr['K'] > curr['D'] else "#008000"
                        k_col2.markdown("**KD指標 (K/D)**", help="**KD 隨機指標**\n\n* **K > D (紅)**：黃金交叉，短線偏多\n* **K < D (綠)**：死亡交叉，短線偏空\n* **>80**：超買\n* **<20**：超賣")
                        k_col2.markdown(f"""
                            <div style="color: {kd_color}; font-size: 26px; font-weight: bold;">
                                {curr['K']:.1f} / {curr['D']:.1f}
                            </div>
                        """, unsafe_allow_html=True)
                    
                    if pd.notna(curr.get('MACD_Hist')):
                        macd_val = curr['MACD_Hist']
                        macd_color = "#FF0000" if macd_val > 0 else "#008000"
                        k_col3.markdown("**MACD柱狀**", help="**MACD 趨勢指標**\n\n* **紅數字**：多方動能 (零軸上)\n* **綠數字**：空方動能 (零軸下)")
                        k_col3.markdown(f"""
                            <div style="color: {macd_color}; font-size: 26px; font-weight: bold;">
                                {macd_val:.2f}
                            </div>
                        """, unsafe_allow_html=True)

                    k_col4.markdown("**量化建議**", help=score_str)
                    k_col4.markdown(f"""
                        <div style="font-size: 20px; font-weight: bold;">
                            <span style="color:{color}">{decision}</span>
                        </div>
                    """, unsafe_allow_html=True)
                    
                    st.divider()
                    with st.expander("📄 詳細診斷報告 (含停損建議)", expanded=True):
                        for r in reports: st.write(r)
                        if not reports: st.write("目前技術面呈現盤整。")
                
                with order_col:
                    st.markdown("##### ⚡ 五檔掛單")
                    if real and (real['asks'] or real['bids']):
                        for ask in reversed(real['asks'][:5]):
                            st.markdown(f"<div style='display:flex; justify-content:space-between; color:#008000;'><span>賣 {ask['price']}</span> <span>{ask['volume']} 張</span></div>", unsafe_allow_html=True)
                        st.markdown("---")
                        for bid in real['bids'][:5]:
                            st.markdown(f"<div style='display:flex; justify-content:space-between; color:#FF0000;'><span>買 {bid['price']}</span> <span>{bid['volume']} 張</span></div>", unsafe_allow_html=True)
                    else: st.caption("盤後或無掛單資料")

                st.subheader(f"📈 {timeframe} 技術圖表")
                tab1, tab2 = st.tabs(["主圖 (K線+均線+通道)", "副圖 (MACD & KD)"])
                
                with tab1:
                    df_plot = df_final.tail(150)
                    
                    # --- 關鍵修正：將日期轉為字串 (Category)，解決無交易日空缺問題 ---
                    # 1. 將日期格式化為字串 (YYYY-MM-DD)
                    df_plot['DateStr'] = df_plot.index.strftime('%Y-%m-%d')
                    
                    fig = go.Figure()
                    
                    # 2. 修改 x 軸資料來源為 DateStr
                    fig.add_trace(go.Candlestick(
                        x=df_plot['DateStr'], # 使用字串軸
                        open=df_plot['Open'],
                        high=df_plot['High'],
                        low=df_plot['Low'],
                        close=df_plot['Close'],
                        increasing_line_color='red', 
                        decreasing_line_color='green',
                        name='K線'
                    ))
                    
                    if 'MA5' in df_plot.columns: fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['MA5'], line=dict(color='#FFD700', width=1), name='MA5'))
                    if 'MA20' in df_plot.columns: fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['MA20'], line=dict(color='#0000FF', width=1), name='MA20'))
                    
                    if 'BB_Upper' in df_plot.columns: fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['BB_Upper'], line=dict(color='purple', width=1, dash='dot'), name='布林上'))
                    if 'BB_Lower' in df_plot.columns: fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['BB_Lower'], line=dict(color='purple', width=1, dash='dot'), name='布林下'))

                    if 'Donchian_High' in df_plot.columns: fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['Donchian_High'], line=dict(color='gray', width=1, dash='dash'), name='唐奇安上'))

                    fig.update_layout(
                        height=500,
                        margin=dict(l=20, r=20, t=20, b=20),
                        xaxis_rangeslider_visible=False,
                        # 3. 強制設定 X 軸為類別型 (Category)，並優化標籤密度
                        xaxis=dict(
                            type='category', 
                            nticks=8,  # 限制顯示標籤數量，避免擁擠
                            tickangle=-0 # 標籤不旋轉
                        )
                    )
                    st.plotly_chart(fig, use_container_width=True)
                
                with tab2:
                    st.caption("KD 指標 (紅K / 藍D)")
                    if 'K' in df_final.columns:
                        st.line_chart(df_final[['K', 'D']].tail(120), color=["#FF0000", "#0000FF"])
                    
                    st.caption("MACD 柱狀圖 (紅=多頭 / 綠=空頭)")
                    if 'MACD_Hist' in df_final.columns:
                        macd_plot = df_final[['MACD_Hist']].tail(120).copy()
                        macd_plot['多方'] = macd_plot['MACD_Hist'].apply(lambda x: x if x > 0 else 0)
                        macd_plot['空方'] = macd_plot['MACD_Hist'].apply(lambda x: x if x < 0 else 0)
                        st.bar_chart(macd_plot[['多方', '空方']], color=["#FF0000", "#008000"])
                    
            else: st.error("查無資料")