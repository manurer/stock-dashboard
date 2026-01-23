import streamlit as st
import pandas as pd
import datetime
import requests
import urllib3
import json
import os
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots # 🔥 新增：匯入子圖功能
import stock_logic  # 匯入共用邏輯

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
                            
                            # 🔥 使用共用邏輯 🔥
                            df_final = stock_logic.calculate_indicators(df_merged)
                            result = stock_logic.analyze_strategy(df_final)
                            
                            signal_text = result["decision"]
                            signal_color = result["color"]
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
                
                # 🔥 使用共用邏輯 🔥
                df_final = stock_logic.calculate_indicators(df_resampled)
                result = stock_logic.analyze_strategy(df_final, timeframe)
                
                # 解包結果
                curr = df_final.iloc[-1]
                decision = result["decision"]
                color = result["color"]
                reports = result["report_list"]
                
                # 重組得分表字串
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
                                # 使用 \n 手動換行，避免 Python 縮排造成 Markdown 誤判為程式碼區塊
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

                                # 🔥 新增這一段：ATR 停損說明
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
                tab1, tab2 = st.tabs(["主圖 (K線+均線+通道+成交量)", "副圖 (MACD & KD)"])
                
                with tab1:
                    df_plot = df_final.tail(150).copy()
                    
                    # 1. 準備繪圖資料
                    df_plot['DateStr'] = df_plot.index.strftime('%Y-%m-%d')
                    
                    # 計算成交量顏色 (漲紅跌綠)
                    # 邏輯：今天收盤 >= 開盤，或比昨天漲 -> 紅色
                    df_plot['Color'] = df_plot.apply(lambda x: '#FF0000' if x['Close'] >= x['Open'] else '#008000', axis=1)

                    # 2. 建立子圖 (2列1行，共用X軸)
                    # row_heights=[0.7, 0.3] 代表上面K線佔70%，下面成交量佔30%
                    fig = make_subplots(
                        rows=2, cols=1, 
                        shared_xaxes=True, 
                        vertical_spacing=0.05, 
                        row_heights=[0.7, 0.3],
                        subplot_titles=(f'{target} 走勢', '成交量')
                    )
                    
                    # 3. 上圖：K線與均線 (Row 1)
                    fig.add_trace(go.Candlestick(
                        x=df_plot['DateStr'],
                        open=df_plot['Open'],
                        high=df_plot['High'],
                        low=df_plot['Low'],
                        close=df_plot['Close'],
                        increasing_line_color='red', 
                        decreasing_line_color='green',
                        name='K線'
                    ), row=1, col=1)
                    
                    if 'MA5' in df_plot.columns: fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['MA5'], line=dict(color='#FFD700', width=1), name='MA5'), row=1, col=1)
                    if 'MA20' in df_plot.columns: fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['MA20'], line=dict(color='#0000FF', width=1), name='MA20'), row=1, col=1)
                    if 'BB_Upper' in df_plot.columns: fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['BB_Upper'], line=dict(color='purple', width=1, dash='dot'), name='布林上'), row=1, col=1)
                    if 'BB_Lower' in df_plot.columns: fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['BB_Lower'], line=dict(color='purple', width=1, dash='dot'), name='布林下'), row=1, col=1)
                    if 'Donchian_High' in df_plot.columns: fig.add_trace(go.Scatter(x=df_plot['DateStr'], y=df_plot['Donchian_High'], line=dict(color='gray', width=1, dash='dash'), name='唐奇安上'), row=1, col=1)

                    # 4. 下圖：成交量 (Row 2)
                    fig.add_trace(go.Bar(
                        x=df_plot['DateStr'],
                        y=df_plot['Volume'],
                        marker_color=df_plot['Color'], # 使用漲跌顏色
                        name='成交量'
                    ), row=2, col=1)

                    # 5. 更新版面設定
                    fig.update_layout(
                        height=600, # 加高一點讓兩個圖都清楚
                        margin=dict(l=20, r=20, t=30, b=20),
                        xaxis_rangeslider_visible=False,
                        # 設定 X 軸 (只對最下方的軸設定即可)
                        xaxis2=dict(
                            type='category', 
                            nticks=8, 
                            tickangle=-0
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