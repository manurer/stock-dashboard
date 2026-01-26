import streamlit as st
import pandas as pd
import datetime
import requests
import urllib3
import json
import os
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import stock_logic
import pytz


# 1. --- 基礎設定 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 請在此填入您的 API KEY
try:
    API_KEY = st.secrets["FUGLE_API_KEY"]
except FileNotFoundError:
    st.error("❌ 找不到 API Key！請確認 secrets.toml 是否設定正確。")
    st.stop()

st.set_page_config(layout="wide", page_title="量化股市戰情室")


# --- 🔥 新增：評分標準說明視窗 (使用 @st.dialog) ---
@st.dialog("📊 AI 量化戰情室 - 評分標準詳解")
def show_score_rules():
    st.markdown("""
    本系統採用 **「攻守兼備」** 的量化評分模型。
    總分無上限，**> 6 分** 為強力買訊；一旦出現 **扣分項**，建議優先避開風險。

    ---
    ### 🛡️ 空方防禦 (Risk Defense) - 優先避開！
    * **-4 分**：💀 **爆量長黑** (跌 >3% 且 量 > 2倍均量) ➤ 主力恐慌出貨。
    * **-3 分**：💔 **跌破季線 (60MA)** ➤ 生命線斷裂，中長線轉空。
    * **-3 分**：💸 **投信大砍** (>500張) 或 **連三賣** ➤ 法人棄養結帳。
    * **-2 分**：🕯️ **空頭吞噬** (昨紅今黑且吃掉漲幅) ➤ 反轉訊號。
    * **-2 分**：🐌 **ADX < 20 (盤整泥沼)** ➤ 無趨勢狀態，均線易失效。
    * **-2 分**：⚠️ **乖離率 > 15%** ➤ 短線過熱，隨時回檔。

    ---
    ### 🏦 法人籌碼 (Chips) - 波段靈魂
    * **+3 分**：🔥 **投信連三買** ➤ 籌碼鎖定，波段趨勢確立。
    * **+3 分**：🚀 **投信首日點火** (且突破關鍵價) ➤ 起漲第一根。
    * **+1 分**：⏳ **投信趨勢偏多** (累積買超或試單) ➤ 籌碼正向。
    * **+1 分**：💰 **OBV > 月均量** ➤ 買盤資金持續進駐。

    ---
    ### 📈 趨勢與動能 (Trend & Momentum)
    * **+3 分**：✨ **5MA 金叉 20MA** ➤ 短線轉強，帶動波段。
    * **+2 分**：✅ **站上 20MA (月線)** ➤ 多頭趨勢確立。
    * **+2 分**：🏹 **KD 低檔金叉** (< 50) ➤ 反彈訊號。
    * **+2 分**：🐂 **MACD 翻紅** (柱狀圖轉正) ➤ 主力動能轉強。
    * **+1 分**：🚄 **ADX > 25 且上升** ➤ 趨勢加速中。

    ---
    ### 🌊 突破與反彈 (Breakout & Rebound)
    * **+3 分**：🔥 **唐奇安突破** (創20日新高) ➤ 突破箱型整理。
    * **+2 分**：🚀 **布林通道突破** (沿上軌噴出) ➤ 強勢飆股特徵。
    * **+1 分**：💎 **負乖離過大** (< -12%) ➤ 短線超跌，留意反彈機會。

    ---
    **💡 操作建議：**
    * **🔴 強力買進 (Score ≥ 6)**：籌碼、技術、動能全數共振。
    * **🟠 偏多操作 (Score ≥ 2)**：大方向向上，可順勢操作。
    * **🟢 建議賣出 (Score ≤ -3)**：觸發防禦扣分機制，嚴禁接刀。
    """)


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
    
    # 1. 取得資料庫最後一筆日期
    last_date = df_merged.index[-1]
    
    # 2. 取得「台北時間」的今天日期
    # 雲端主機通常是 UTC，必須強制轉成 Asia/Taipei，否則早上會被誤判成昨天
    tz = pytz.timezone('Asia/Taipei')
    today = datetime.datetime.now(tz).date()
    today_ts = pd.Timestamp(today) # 轉成 Pandas Timestamp 以便比較
    
    current_price = realtime_data['price']
    current_vol = realtime_data.get('volume', 0) # 盤中累積成交量(估算)
    
    # 3. 判斷邏輯：如果歷史資料還停在「比今天早」的日子 (例如 1/23 < 1/26)
    if last_date.date() < today:
        # 建立今天的新 K 棒 (Open/High/Low/Close 先暫時都填現價，Volume 填 0 或 API 給的量)
        # 注意：Fugle intraday quote 裡的 volume 通常是累積量，但也許要另外處理，這裡先暫時設 0 或用累積
        new_row = pd.DataFrame({
            "Open": [current_price], 
            "High": [current_price], 
            "Low": [current_price], 
            "Close": [current_price], 
            "Volume": [0] # 暫時填 0，因為 K 線圖的 Volume 通常是看歷史，盤中即時量要看右邊數據
        }, index=[today_ts])
        
        df_merged = pd.concat([df_merged, new_row])
    
    # 4. 更新 (無論是剛新增的，或是原本就有的今天)
    # 隨時更新今天的收盤價、最高、最低
    target_date = df_merged.index[-1]
    df_merged.loc[target_date, 'Close'] = current_price
    
    if current_price > df_merged.loc[target_date, 'High']:
        df_merged.loc[target_date, 'High'] = current_price
        
    if current_price < df_merged.loc[target_date, 'Low']:
        df_merged.loc[target_date, 'Low'] = current_price
            
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

 # --- 🔥 新增：在移除按鈕下方，加入說明按鈕 ---
st.sidebar.markdown("---") # 畫一條分隔線，比較好看
if st.sidebar.button("❓ 評分標準說明"):
    show_score_rules()


if page == "📊 戰情總覽":
    st.title("📊 多檔股票戰情總覽")
    if not st.session_state.watchlist: st.info("清單是空的")
    else:
        # 1. 批次資料處理 (Batch Processing)
        progress_bar = st.progress(0, text="正在啟動戰情掃描雷達...")
        results_cache = [] 
        total_stocks = len(st.session_state.watchlist)
        
        for i, symbol in enumerate(st.session_state.watchlist):
            # 更新進度條
            percent = int(((i) / total_stocks) * 100)
            progress_bar.progress(percent, text=f"正在分析 {symbol} ({i+1}/{total_stocks})...")
            
            time.sleep(1.0) 
            
            real_data = get_realtime_quote_full(symbol)
            stock_result = {
                "symbol": symbol,
                "name": symbol,
                "price": 0.0,
                "change": 0.0,
                "pct": 0.0,
                "score": 0,
                "signal": "資料不足",
                "color": "#888",
                "stop_loss": None,
                "raw_real": None
            }
            
            if real_data:
                stock_result["name"] = real_data['name']
                stock_result["price"] = real_data['price']
                stock_result["change"] = real_data['change']
                stock_result["pct"] = real_data['change_percent']
                stock_result["raw_real"] = real_data
                
                hist_data = get_historical_data(symbol)
                if hist_data is not None:
                    try:
                        df_merged = merge_realtime_data(hist_data, real_data)
                        
                        # 🔥 傳入 symbol 讓 FinMind 抓資料
                        df_final = stock_logic.calculate_indicators(df_merged, symbol)
                        logic_res = stock_logic.analyze_strategy(df_final)
                        
                        stock_result["score"] = logic_res["score"]
                        stock_result["signal"] = logic_res["decision"]
                        stock_result["color"] = logic_res["color"]
                        stock_result["stop_loss"] = logic_res["stop_loss"]
                    except Exception as e:
                        print(f"Error analyzing {symbol}: {e}")
            
            results_cache.append(stock_result)

        progress_bar.empty()

        # 2. 顯示戰情總表
        st.subheader("📋 全域戰情排行榜")
        
        if results_cache:
            df_summary = pd.DataFrame(results_cache)
            display_df = df_summary[["symbol", "name", "price", "pct", "score", "signal", "stop_loss"]].copy()
            display_df.columns = ["代號", "名稱", "現價", "漲跌幅(%)", "AI總分", "訊號", "建議停損"]
            
            st.dataframe(
                display_df.style.background_gradient(subset=["AI總分"], cmap="RdYlGn"), 
                width='stretch', # 🔥 修正: 改用 width='stretch'
                hide_index=True,
                column_config={
                    "現價": st.column_config.NumberColumn(format="%.2f"),
                    "漲跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
                    "建議停損": st.column_config.NumberColumn(format="%.2f"),
                    "AI總分": st.column_config.NumberColumn(help="越高分越好，滿分 6 分以上為強力買進"),
                }
            )

        st.divider()

        # 3. 顯示卡片牆
        st.subheader("🃏 個股詳細卡片")
        cols = st.columns(4)
        for i, data in enumerate(results_cache):
            with cols[i % 4]:
                symbol = data["symbol"]
                name = data["name"]
                price = data["price"]
                change = data["change"]
                pct = data["pct"]
                signal_text = data["signal"]
                signal_color = data["color"]
                
                price_color = "#FF0000" if change > 0 else "#008000" if change < 0 else "#666666"
                
                st.markdown(f"""
                <div style="border:1px solid #ddd; padding:10px; border-radius:10px; margin-bottom:10px; background-color:#1E1E1E;">
                    <div style="font-size:16px; font-weight:bold; color:#FFF;">
                        {symbol} {name}
                    </div>
                    <div style="margin-top:5px; margin-bottom:5px;">
                        <span style="background-color:{signal_color}; color:white; padding:2px 8px; border-radius:4px; font-size:12px;">
                            {signal_text} ({data['score']}分)
                        </span>
                    </div>
                    <div style="font-size:24px; font-weight:bold; color:{price_color};">
                        {price}
                    </div>
                    <div style="font-size:14px; color:{price_color};">
                        {change} ({pct}%)
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                st.button(f"🔍 詳細 {name}", key=f"btn_{symbol}", on_click=go_to_analysis, args=(symbol,))


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
        timeframe = st.radio("⏳ 選擇K線週期", ["日線", "週線", "月線"], index=0, horizontal=True)
        
        with st.spinner(f'正在分析：{target} ({timeframe})...'):
            df_h = get_historical_data(target)
            real = get_realtime_quote_full(target)
            
            if df_h is not None:
                df_merged = merge_realtime_data(df_h, real)
                df_resampled = resample_timeframe(df_merged, timeframe)
                
                # 🔥 傳入 target 讓 FinMind 抓資料
                df_final = stock_logic.calculate_indicators(df_resampled, target)
                result = stock_logic.analyze_strategy(df_final, timeframe)
                
                curr = df_final.iloc[-1]
                decision = result["decision"]
                color = result["color"]
                reports = result["report_list"]
                
                score_str = "**📝 詳細得分表：**\n\n"
                for item, pts in result["score_details"]:
                    score_str += f"- {item}: {pts}\n"
                score_str += f"\n**🏆 總分：{result['score']} 分**"
                
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
                    
                    with st.expander("📄 詳細診斷報告 (含停損建議)", expanded=True):
                        for r in reports:
                            if "OBV" in r:
                                obv_msg = (
                                    "📊 **【OBV 能量潮原理】**\n"
                                    "它是從一年前開始累計的「籌碼總量」。\n"
                                    "邏輯：紅K(漲)就加量，黑K(跌)就扣量。\n\n"
                                    "💡 **實戰意義：抓主力**\n"
                                    "若股價還在盤整，但 OBV 曲線率先創高，"
                                    "代表主力正在偷吃貨，是大漲前兆！"
                                )
                                st.markdown(r, help=obv_msg)
                            elif "ADX" in r:
                                adx_msg = (
                                    "💪 **【ADX 趨勢強度】**\n"
                                    "• < 20 (盤整)：無趨勢，均線易失效。\n"
                                    "• > 25 (趨勢)：趨勢成形，順勢操作。\n"
                                    "• 數值向上：代表趨勢正在加速中！"
                                )
                                st.markdown(r, help=adx_msg)
                            elif "ATR" in r:
                                atr_msg = (
                                    "🛡️ **【ATR 波動率停損】**\n"
                                    "公式：收盤價 - (2 × ATR)\n\n"
                                    "💡 **原理說明：**\n"
                                    "ATR 代表這檔股票近期的「正常震幅」。\n"
                                    "設定 2 倍 ATR 的寬度，是為了留給股價\n"
                                    "「正常呼吸」的空間，避免被一般雜訊洗出場。\n"
                                    "若跌破此價位，代表趨勢真的反轉了。"
                                )
                                st.markdown(r, help=atr_msg)
                            else:
                                st.markdown(r)

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
                tab1, tab2 = st.tabs(["主圖 (K線+均線+通道+成交量+籌碼)", "副圖 (MACD & KD)"])
                
                with tab1:
                    df_plot = df_final.tail(150).copy()
                    
                    df_plot['DateStr'] = df_plot.index.strftime('%Y-%m-%d')
                    df_plot['Color'] = df_plot.apply(lambda x: '#FF0000' if x['Close'] >= x['Open'] else '#008000', axis=1)

                    # --- 1. 建立子圖 (3列) ---
                    fig = make_subplots(
                        rows=3, cols=1, 
                        shared_xaxes=True, # 🔥 關鍵：讓三張圖共用 X 軸
                        vertical_spacing=0.05, 
                        row_heights=[0.5, 0.25, 0.25], # 調整高度比例 (主圖大一點)
                        subplot_titles=(f'{target} 走勢', '成交量', '法人籌碼 (投信)')
                    )

                    # --- 2. 準備 Fibonacci 數值 ---
                    recent_df = df_plot.tail(60)
                    high_price = recent_df['High'].max()
                    low_price = recent_df['Low'].min()
                    diff = high_price - low_price
                    fib_0382 = high_price - (diff * 0.382)
                    fib_0618 = high_price - (diff * 0.618)
                    
                    # 畫 Fibonacci 線 (加在第1列)
                    fig.add_shape(type="line", x0=recent_df['DateStr'].iloc[0], y0=fib_0382, x1=recent_df['DateStr'].iloc[-1], y1=fib_0382,
                        line=dict(color="orange", width=1, dash="dot"), row=1, col=1)
                    fig.add_annotation(x=recent_df['DateStr'].iloc[-1], y=fib_0382, text="Fib 0.382", showarrow=False, xanchor="left", font=dict(color="orange"), row=1, col=1)

                    fig.add_shape(type="line", x0=recent_df['DateStr'].iloc[0], y0=fib_0618, x1=recent_df['DateStr'].iloc[-1], y1=fib_0618,
                        line=dict(color="green", width=2, dash="dash"), row=1, col=1)
                    fig.add_annotation(x=recent_df['DateStr'].iloc[-1], y=fib_0618, text="Fib 0.618 (支撐)", showarrow=False, xanchor="left", font=dict(color="green"), row=1, col=1)

                    # --- 3. 繪製圖表 ---
                    
                    # Row 1: K線
                    fig.add_trace(go.Candlestick(
                        x=df_plot['DateStr'],
                        open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'],
                        increasing_line_color='red', decreasing_line_color='green', name='K線'
                    ), row=1, col=1)
                    
                    if 'MA5' in df_plot.columns: fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['MA5'], line=dict(color='#FFD700', width=1), name='MA5'), row=1, col=1)
                    if 'MA20' in df_plot.columns: fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['MA20'], line=dict(color='#0000FF', width=1), name='MA20'), row=1, col=1)
                    if 'BB_Upper' in df_plot.columns: fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['BB_Upper'], line=dict(color='purple', width=1, dash='dot'), name='布林上'), row=1, col=1)
                    if 'BB_Lower' in df_plot.columns: fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['BB_Lower'], line=dict(color='purple', width=1, dash='dot'), name='布林下'), row=1, col=1)

                    # Row 2: 成交量
                    fig.add_trace(go.Bar(
                        x=df_plot['DateStr'], y=df_plot['Volume'],
                        marker_color=df_plot['Color'], name='成交量'
                    ), row=2, col=1)

                    # Row 3: 法人籌碼 (投信)
                    if 'Trust_Net' in df_plot.columns:
                        trust_color = df_plot['Trust_Net'].apply(lambda x: 'red' if x > 0 else 'green')
                        fig.add_trace(go.Bar(
                            x=df_plot['DateStr'], 
                            y=df_plot['Trust_Net'],
                            marker_color=trust_color,
                            name='投信買賣超'
                        ), row=3, col=1)
                    
                    # 投信累計 (線圖)
                    if 'Trust_Cum' in df_plot.columns:
                        fig.add_trace(go.Scatter(
                            x=df_plot['DateStr'],
                            y=df_plot['Trust_Cum'],
                            line=dict(color='orange', width=2),
                            name='投信庫存(累計)',
                            yaxis='y4'
                        ), row=3, col=1)

                    # --- 4. 版面設定 (關鍵優化) ---
                    
                    # 🔥 強制所有 X 軸都使用「類別」模式 (Category)
                    # 這樣可以 1.完全對齊 2.自動隱藏週末空白
                    fig.update_xaxes(type='category', tickmode='auto', nticks=10)
                    
                    fig.update_layout(
                        height=800,
                        margin=dict(l=20, r=20, t=30, b=20),
                        xaxis_rangeslider_visible=False,
                        
                        # 圖例設定 (放在最上面)
                        showlegend=True, 
                        legend=dict(
                            orientation="h",
                            yanchor="bottom",
                            y=1.02,
                            xanchor="right",
                            x=1
                        )
                    )
                    st.plotly_chart(fig, use_container_width=True)

                    st.info("""
                    **📉 觀察重點：**
                    * **三圖連動**：現在拖動 K 線圖，下面的成交量與投信籌碼會完全同步縮放。
                    * **Fibonacci**：橘色(0.382)為強勢回檔，綠色(0.618)為黃金買點。
                    * **🏦 投信籌碼**：紅柱連發代表投信認養，橘線(累計庫存)創新高代表籌碼穩定集中。
                    """)

                
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