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

# --- 評分標準說明視窗 ---
@st.dialog("📊 AI 量化戰情室 - 評分標準詳解 (v10.1)")
def show_score_rules():
    st.markdown("""
    本系統採用 **「攻守兼備」** 的量化評分模型，特別針對 **波段抄底** 優化。
    總分無上限，**> 6 分** 為強力買訊；一旦出現 **扣分項**，建議優先避開風險。

    ---
    ### 🛡️ 空方防禦 (Risk Defense) - 優先避開！
    * **-4 分**：💀 **爆量長黑** (跌 >3% 且 量 > 2倍均量) ➤ 主力恐慌出貨。
    * **-3 分**：⚔️ **土洋對作** (外資賣 >1000張 且 融資增 >500張) ➤ 大戶倒貨給散戶。
    * **-3 分**：☠️ **散戶接刀** (股價破月線 且 融資增加) ➤ 籌碼極度不安定。
    * **-3 分**：🧨 **融資爆表** (使用率 > 60%) ➤ 多殺多風險極高。
    * **-3 分**：💔 **跌破季線 (60MA)** ➤ 生命線斷裂，中長線轉空 (低位階僅扣1分)。
    * **-3 分**：💀 **空頭排列** (5MA < 20MA < 60MA) ➤ 均線蓋頭反壓。
    * **-3 分**：💸 **投信大砍** (>500張) ➤ 法人棄養結帳。
    * **-1 分**：⚠️ **營收衰退** (YoY < -20%) ➤ 基本面疲弱，抄底需謹慎。

    ---
    ### 🏦 法人籌碼 (Chips) - 波段靈魂
    * **+3 分**：🔥 **投信連三買** (且站上月線) ➤ 籌碼鎖定，攻擊發起。
    * **+3 分**：🚀 **投信首日點火** (且突破關鍵價) ➤ 起漲第一根。
    * **+2 分**：🛡️ **投信低檔建倉** (位階低且連買) ➤ 潛力極大，視為強力佈局。
    * **+1 分**：🛡️ **投信低檔護盤** (月線下連買) ➤ 視為防守單。
    * **+1 分**：💰 **OBV > 月均量** ➤ 買盤資金持續進駐。

    ---
    ### 📈 趨勢與動能 (Trend & Momentum)
    * **+4 分**：✨ **低檔金叉** (位階 < 20% 且 5MA 金叉 20MA) ➤ 黃金買點！
    * **+3 分**：✨ **5MA 金叉 20MA** ➤ 短線轉強，帶動波段。
    * **+2 分**：✅ **站上 20MA (月線)** ➤ 多頭趨勢確立。
    * **+2 分**：🏹 **KD 低檔金叉** (< 50) ➤ 反彈訊號。
    * **+2 分**：🐂 **MACD 翻紅** (柱狀圖轉正) ➤ 主力動能轉強。
    * **+1 分**：🚄 **ADX > 30 且上升** ➤ 趨勢加速中。

    ---
    ### ⚖️ 智慧乖離與基本面
    * **+1 分**：📊 **營收高成長** (YoY > 20%) ➤ 基本面強勁保護。
    * **-3 分**：⚠️ **乖離極大** (> 18%) ➤ 絕對過熱，強烈建議獲利了結。
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
    last_date = df_merged.index[-1]
    
    tz = pytz.timezone('Asia/Taipei')
    today = datetime.datetime.now(tz).date()
    today_ts = pd.Timestamp(today) 
    
    current_price = realtime_data['price']
    
    if last_date.date() < today:
        new_row = pd.DataFrame({
            "Open": [current_price], 
            "High": [current_price], 
            "Low": [current_price], 
            "Close": [current_price], 
            "Volume": [0] 
        }, index=[today_ts])
        
        df_merged = pd.concat([df_merged, new_row])
    
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

# 🔥 新增：回測嚴格度拉桿
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 策略設定")
bt_threshold = st.sidebar.slider(
    "回測買進門檻 (分)", 
    min_value=2, 
    max_value=6, 
    value=5, # 預設改成您喜歡的 5
    help="設定回測時，AI總分多少以上才買進。分數越高越嚴格，勝率通常越高，但次數越少。"
)
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

st.sidebar.markdown("---")
if st.sidebar.button("❓ 評分標準說明"):
    show_score_rules()

if page == "📊 戰情總覽":
    st.title("📊 多檔股票戰情總覽")
    if not st.session_state.watchlist: st.info("清單是空的")
    else:
        # 1. 批次資料處理
        progress_bar = st.progress(0, text="正在啟動戰情掃描雷達...")
        results_cache = [] 
        total_stocks = len(st.session_state.watchlist)
        
        for i, symbol in enumerate(st.session_state.watchlist):
            # 更新進度條
            percent = int(((i) / total_stocks) * 100)
            progress_bar.progress(percent, text=f"正在分析 {symbol} ({i+1}/{total_stocks})...")
            
            time.sleep(0.5) 
            
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
                "raw_real": None,
                "win_rate": 0.0
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
                        df_final = stock_logic.calculate_indicators(df_merged, symbol)
                        logic_res = stock_logic.analyze_strategy(df_final)
                        
                        stock_result["score"] = logic_res["score"]
                        stock_result["signal"] = logic_res["decision"]
                        stock_result["color"] = logic_res["color"]
                        stock_result["stop_loss"] = logic_res["stop_loss"]

                        # --- 🔥 回測運算 ---
                        bt_logs = stock_logic.run_backtest(df_final, days_to_test=180, threshold=bt_threshold)
                        valid_trades = [log for log in bt_logs if log['後5日漲幅'] is not None]
                        
                        if valid_trades:
                            win_count = sum(1 for log in valid_trades if log['後5日漲幅'] > 0)
                            win_rate = (win_count / len(valid_trades)) * 100
                            stock_result["win_rate"] = win_rate
                        else:
                            stock_result["win_rate"] = 0.0

                    except Exception as e:
                        print(f"Error analyzing {symbol}: {e}")
            
            results_cache.append(stock_result)

        progress_bar.empty()

        # 2. 顯示戰情總表
        st.subheader("📋 全域戰情排行榜")
        if results_cache:
            df_summary = pd.DataFrame(results_cache)
            display_df = df_summary[["symbol", "name", "price", "pct", "score", "signal", "win_rate"]].copy()
            display_df.columns = ["代號", "名稱", "現價", "漲跌幅(%)", "AI總分", "訊號", "勝率(半年)"]
            
            st.dataframe(
                display_df.style.background_gradient(subset=["AI總分"], cmap="RdYlGn"), 
                width='stretch', 
                hide_index=True,
                column_config={
                    "現價": st.column_config.NumberColumn(format="%.2f"),
                    "漲跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
                    "AI總分": st.column_config.NumberColumn(help="越高分越好"),
                    "勝率(半年)": st.column_config.NumberColumn(format="%.1f%%"),
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
                win_rate = data["win_rate"]

                if win_rate >= 60: 
                    win_color = "#FF4B4B"
                    win_icon = "🔥"
                elif win_rate <= 40: 
                    win_color = "#00C853"
                    win_icon = "❄️"
                else: 
                    win_color = "#888888"
                    win_icon = "⚖️"
                
                win_text = "尚無交易" if win_rate == 0 else f"{win_icon} 勝率 {win_rate:.0f}%"
                price_color = "#FF0000" if change > 0 else "#008000" if change < 0 else "#666666"
                
                # 🔥 關鍵修正：移除 HTML 字串的縮排，解決代碼區塊顯示問題
                card_html = f"""
<div style="border:1px solid #444; padding:12px; border-radius:12px; margin-bottom:15px; background-color:#1E1E1E; box-shadow: 2px 2px 5px rgba(0,0,0,0.3);">
    <div style="font-size:16px; font-weight:bold; color:#FFF; margin-bottom:4px;">
        {symbol} {name}
    </div>
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <span style="background-color:{signal_color}; color:white; padding:3px 8px; border-radius:4px; font-size:12px; font-weight:bold;">
            {signal_text}
        </span>
        <span style="color:#AAA; font-size:12px;">
            {data['score']}分
        </span>
    </div>
    <div style="font-size:26px; font-weight:bold; color:{price_color}; line-height:1.2;">
        {price}
    </div>
    <div style="font-size:14px; color:{price_color}; margin-bottom:10px;">
        {change} ({pct}%)
    </div>
    <div style="border-top:1px solid #333; padding-top:8px; margin-top:8px; display:flex; justify-content:space-between; align-items:center;">
        <span style="color:#DDD; font-size:13px;">歷史回測</span>
        <span style="color:{win_color}; font-weight:bold; font-size:14px; background-color:rgba(255,255,255,0.1); padding:2px 6px; border-radius:4px;">
            {win_text}
        </span>
    </div>
</div>
"""
                st.markdown(card_html, unsafe_allow_html=True)
                
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
                                obv_msg = "📊 **【OBV 能量潮原理】**\n籌碼總量指標。紅K加量，黑K扣量。\n💡 若股價盤整但 OBV 創高，代表主力偷吃貨。"
                                st.markdown(r, help=obv_msg)
                            elif "ADX" in r:
                                adx_msg = "💪 **【ADX 趨勢強度】**\n<20 盤整，>25 趨勢成形。數值向上代表趨勢加速。"
                                st.markdown(r, help=adx_msg)
                            elif "ATR" in r:
                                atr_msg = "🛡️ **【ATR 波動率停損】**\n公式：收盤價 - (2 × ATR)。給予股價正常呼吸空間。"
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
                tab1, tab2 = st.tabs(["主圖 (K線+籌碼+融資)", "副圖 (MACD & KD)"])
                
                with tab1:
                    df_plot = df_final.tail(150).copy()
                    df_plot['DateStr'] = df_plot.index.strftime('%Y-%m-%d')
                    df_plot['Color'] = df_plot.apply(lambda x: '#FF0000' if x['Close'] >= x['Open'] else '#008000', axis=1)

                    fig = make_subplots(
                        rows=4, cols=1, 
                        shared_xaxes=True, 
                        vertical_spacing=0.03, 
                        row_heights=[0.4, 0.2, 0.2, 0.2], 
                        subplot_titles=(f'{target} 走勢', '成交量', '法人籌碼 (投信)', '散戶指標 (融資餘額)')
                    )

                    recent_df = df_plot.tail(60)
                    high_price = recent_df['High'].max()
                    low_price = recent_df['Low'].min()
                    diff = high_price - low_price
                    fib_0382 = high_price - (diff * 0.382)
                    fib_0618 = high_price - (diff * 0.618)
                    
                    fig.add_shape(type="line", x0=recent_df['DateStr'].iloc[0], y0=fib_0382, x1=recent_df['DateStr'].iloc[-1], y1=fib_0382,
                        line=dict(color="orange", width=1, dash="dot"), row=1, col=1)
                    fig.add_annotation(x=recent_df['DateStr'].iloc[-1], y=fib_0382, text="Fib 0.382", showarrow=False, xanchor="left", font=dict(color="orange"), row=1, col=1)

                    fig.add_shape(type="line", x0=recent_df['DateStr'].iloc[0], y0=fib_0618, x1=recent_df['DateStr'].iloc[-1], y1=fib_0618,
                        line=dict(color="green", width=2, dash="dash"), row=1, col=1)
                    fig.add_annotation(x=recent_df['DateStr'].iloc[-1], y=fib_0618, text="Fib 0.618 (支撐)", showarrow=False, xanchor="left", font=dict(color="green"), row=1, col=1)

                    fig.add_trace(go.Candlestick(
                        x=df_plot['DateStr'],
                        open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'],
                        increasing_line_color='red', decreasing_line_color='green', name='K線'
                    ), row=1, col=1)
                    
                    if 'MA5' in df_plot.columns: fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['MA5'], line=dict(color='#FFD700', width=1), name='MA5'), row=1, col=1)
                    if 'MA20' in df_plot.columns: fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['MA20'], line=dict(color='#0000FF', width=1), name='MA20'), row=1, col=1)
                    if 'MA60' in df_plot.columns: fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['MA60'], line=dict(color='#008000', width=1, dash='dot'), name='季線'), row=1, col=1)
                    if 'BB_Upper' in df_plot.columns: fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['BB_Upper'], line=dict(color='purple', width=1, dash='dot'), name='布林上'), row=1, col=1)
                    if 'BB_Lower' in df_plot.columns: fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['BB_Lower'], line=dict(color='purple', width=1, dash='dot'), name='布林下'), row=1, col=1)

                    fig.add_trace(go.Bar(x=df_plot['DateStr'], y=df_plot['Volume'], marker_color=df_plot['Color'], name='成交量'), row=2, col=1)

                    if 'Trust_Net' in df_plot.columns:
                        trust_color = df_plot['Trust_Net'].apply(lambda x: 'red' if x > 0 else 'green')
                        fig.add_trace(go.Bar(x=df_plot['DateStr'], y=df_plot['Trust_Net'], marker_color=trust_color, name='投信買賣超'), row=3, col=1)
                    if 'Trust_Cum' in df_plot.columns:
                        fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['Trust_Cum'], line=dict(color='orange', width=2), name='投信庫存'), row=3, col=1)

                    if 'Margin_Balance' in df_plot.columns:
                        fig.add_trace(go.Scatter(
                            x=df_plot['DateStr'], y=df_plot['Margin_Balance'],
                            mode='lines', fill='tozeroy', line=dict(color='#8B008B', width=2), name='融資餘額'
                        ), row=4, col=1)

                    fig.update_xaxes(type='category', tickmode='auto', nticks=10)
                    fig.update_layout(height=900, margin=dict(l=20, r=20, t=30, b=20), xaxis_rangeslider_visible=False, showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                    st.plotly_chart(fig, use_container_width=True)

                    st.info("**📉 觀察重點：**\n* **投信**：紅柱連發與橘線創高。\n* **融資**：股價跌但紫色山變高 = 散戶接刀。\n* **Fibonacci**：0.618 (綠線) 為黃金回檔點。")
                
                with tab2:
                    st.caption("KD 指標 (紅K / 藍D)")
                    if 'K' in df_final.columns: st.line_chart(df_final[['K', 'D']].tail(120), color=["#FF0000", "#008000"])
                    st.caption("MACD 柱狀圖 (紅多/綠空)")
                    if 'MACD_Hist' in df_final.columns:
                        macd_plot = df_final[['MACD_Hist']].tail(120).copy()
                        macd_plot['多方'] = macd_plot['MACD_Hist'].apply(lambda x: x if x > 0 else 0)
                        macd_plot['空方'] = macd_plot['MACD_Hist'].apply(lambda x: x if x < 0 else 0)
                        st.bar_chart(macd_plot[['多方', '空方']], color=["#FF0000", "#008000"])

                st.markdown("---")
                st.subheader("🧪 策略時光機 (歷史回測)")
                st.caption("驗證過去 60 個交易日，若依照 AI 建議 (分數≥2) 於「隔日開盤」買進的績效。")

                if st.button("🚀 開始回測驗證"):
                    with st.spinner("正在穿越時空，計算歷史績效..."):
                        logs = stock_logic.run_backtest(df_final, days_to_test=60, threshold=bt_threshold)
                        if logs:
                            df_bt = pd.DataFrame(logs)
                            st.write(f"📊 過去 60 天內，AI 共發出 **{len(df_bt)}** 次偏多訊號")
                            
                            valid_trades = df_bt.dropna(subset=['後5日漲幅'])
                            if not valid_trades.empty:
                                win_count = len(valid_trades[valid_trades['後5日漲幅'] > 0])
                                win_rate = (win_count / len(valid_trades)) * 100
                                avg_return = valid_trades['後5日漲幅'].mean()
                                col_res1, col_res2 = st.columns(2)
                                col_res1.metric("短線勝率 (5日)", f"{win_rate:.1f}%")
                                col_res2.metric("平均報酬 (5日)", f"{avg_return:.2f}%")
                            
                            def highlight_ret(val):
                                if val is None or pd.isna(val): return ''
                                color = 'red' if val > 0 else 'green'
                                return f'color: {color}'

                            st.dataframe(df_bt.style.map(highlight_ret, subset=['後5日漲幅', '後10日漲幅', '後20日漲幅']).format("{:.2f}%", subset=['後5日漲幅', '後10日漲幅', '後20日漲幅']), width='stretch')
                        else:
                            st.warning("過去 60 天內，AI 沒有出現過買進訊號。")
            else: st.error("查無資料")