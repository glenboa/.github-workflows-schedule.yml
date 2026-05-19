import os
import requests
import json
import re
import time
from datetime import datetime, timezone, timedelta
from alpaca.trading.client import TradingClient
from alpaca.data.client import StockDataClient
from alpaca.data.requests import StockLatestTradeRequest
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus

# 1. Initialize API Keys and System Configurations
FMP_KEY = os.getenv("FMP_API_KEY")
ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY")
AI_KEY = os.getenv("DEEPSEEK_API_KEY")

GLOBAL_TICKERS = ["SPY", "NVDA", "AAPL", "MSFT"]
STATE_FILE = "portfolio_state.json"

# 2. State Engine Helper Functions
def load_portfolio_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            print("⚠️ State file corrupted or empty. Re-initializing empty dictionary.")
            return {}
    return {}

def save_portfolio_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=4)
    except Exception as e:
        print(f"❌ Critical Error saving state file: {e}")

# 3. Mathematical Volatility Engine (ATR)
def calculate_atr_and_get_data(ticker):
    today = datetime.now(timezone.utc)
    start_date = (today - timedelta(days=15)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")
    
    chart_url = "https://financialmodelingprep.com/stable/historical-price-eod/full"
    chart_params = {"symbol": ticker, "from": start_date, "to": end_date, "apikey": FMP_KEY}
    
    response = requests.get(chart_url, params=chart_params).json()
    
    if not isinstance(response, list) or len(response) < 6:
        print(f"--- FMP API Error Response for {ticker} ---")
        print(response)
        print("------------------------------------------")
        raise KeyError(f"FMP Stable API returned an insufficient historical structure for {ticker}.")
        
    chart_data = response[:5]  # Most recent 5 days for the AI prompt
    
    # ATR Math Loop: Calculate True Range across the last 5 full sessions
    true_ranges = []
    for i in range(5):
        high = float(response[i].get("high", 0))
        low = float(response[i].get("low", 0))
        close_prev = float(response[i+1].get("close", 0)) if i+1 < len(response) else low
        
        tr = max(high - low, abs(high - close_prev), abs(low - close_prev))
        true_ranges.append(tr)
        
    atr = sum(true_ranges) / len(true_ranges)
    
    # Economic Calendar Retrieval
    calendar_url = "https://financialmodelingprep.com/stable/economic-calendar"
    calendar_params = {"from": end_date, "to": end_date, "apikey": FMP_KEY}
    calendar_events = []
    
    try:
        calendar_response = requests.get(calendar_url, params=calendar_params).json()
        if isinstance(calendar_response, list):
            calendar_events = [
                {"event": e.get("event"), "country": e.get("country"), "actual": e.get("actual")}
                for e in calendar_response if e.get("impact") in ["Medium", "High"]
            ]
    except Exception as e:
        print(f"⚠️ Warning: Could not parse economic calendar data: {e}")

    return chart_data, calendar_events, atr

# 4. Neural Network Communication Gate
def ask_deepseek(ticker, charts, calendar):
    headers = {"Authorization": f"Bearer {AI_KEY}", "Content-Type": "application/json"}
    prompt = f"""
    Analyze this asset: {ticker}
    Recent Candlestick Data: {charts}
    Today's Global High-Impact Economic Calendar Events: {calendar}
    Task: Evaluate the technical data alongside the global macroeconomic environment. Determine if the asset price will close higher or lower tomorrow.
    You must output exactly valid JSON format only, with no other conversational text or markdown code blocks.
    Format: {{"action": "BUY", "confidence": 0.58}} or {{"action": "HOLD", "confidence": 0.00}}
    """
    data = {
        "model": "deepseek-ai/DeepSeek-R1",
        "messages": [{"role": "user", "content": prompt}]
    }
    
    response = requests.post("https://api.deepinfra.com/v1/openai/chat/completions", headers=headers, json=data).json()
    if 'choices' not in response:
        raise KeyError("Could not find 'choices' in DeepSeek response.")
        
    ai_text = response['choices'][0]['message']['content'].strip()
    json_blocks = re.findall(r"\{.*?\}", ai_text, re.DOTALL)
    if not json_blocks:
        raise ValueError("Could not find any JSON structural blocks in the AI response.")
        
    return json.loads(json_blocks[-1])

# 5. Passive Portfolio Risk & Exit Monitor
def monitor_active_portfolio_exits(trading_client, state):
    print("\n🔍 [RISK MONITOR] Auditing active open positions against volatility limits...")
    
    try:
        open_positions = trading_client.get_all_positions()
    except Exception as e:
        print(f"⚠️ Could not pull open positions from Alpaca: {e}. Skipping risk check step.")
        return state

    active_symbols = [p.symbol for p in open_positions]
    
    # Purge stale tickers from state if they were liquidated manually outside the script
    state = {ticker: data for ticker, data in state.items() if ticker in active_symbols}

    for position in open_positions:
        ticker = position.symbol
        current_price = float(position.current_price)
        
        try:
            _, _, atr = calculate_atr_and_get_data(ticker)
        except Exception:
            atr = current_price * 0.02 # Safe volatility fallback if API fails
            
        if ticker not in state:
            state[ticker] = {
                "highest_recorded_price": current_price,
                "sessions_held": 0,
                "atr_at_entry": atr
            }
            
        state[ticker]["sessions_held"] += 1
        
        if current_price > state[ticker]["highest_recorded_price"]:
            state[ticker]["highest_recorded_price"] = current_price
            
        highest_tracked = state[ticker]["highest_recorded_price"]
        saved_atr = state[ticker]["atr_at_entry"]
        
        # Chandelier Trailing Floor calculation (2.5x ATR trailing below the peak)
        trailing_stop_floor = round(highest_tracked - (2.5 * saved_atr), 2)
        
        print(f"📊 {ticker} Tracking -> Current: ${current_price:.2f} | Trailing Stop Floor: ${trailing_stop_floor:.2f} | Sessions Active: {state[ticker]['sessions_held']}/4")

        # Time-Decay Check
        if state[ticker]["sessions_held"] >= 4:
            print(f"⏳ [TIME EXCLUSION] Time-decay threshold matched for {ticker}. Liquidating...")
            trading_client.close_position(ticker)
            if ticker in state: del state[ticker]
            continue

        # Volatility Stop Execution Check
        if current_price <= trailing_stop_floor:
            print(f"🚨 [VOLATILITY BREACH] {ticker} cracked the trailing floor of ${trailing_stop_floor:.2f}! Liquidating...")
            trading_client.close_position(ticker)
            if ticker in state: del state[ticker]
            continue
            
    return state

# 6. Primary Execution Engine Loop
def process_scans_and_entries(ticker, trading_client, data_client, state):
    print(f"\n🔄 [SCANNING] Fetching multi-frame technical structures for {ticker}...")
    chart_data, calendar_events, atr = calculate_atr_and_get_data(ticker)
    
    print(f"🧠 [ANALYZING] Querying DeepSeek-R1 Macro Engine for {ticker}...")
    decision = ask_deepseek(ticker, str(chart_data), str(calendar_events))
    print(f"📊 [AI OUTPUT] {ticker} Evaluation payload: {decision}")
    
    action = decision.get("action")
    confidence = decision.get("confidence", 0.0)
    
    if action in ["BUY", "HOLD"]:
        print(f"🎯 [EXECUTE] Active cycle triggered. Validating session entry duplicates...")
        
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        order_filter = GetOrdersRequest(status=QueryOrderStatus.ALL, side=OrderSide.BUY, nested=False)
        all_orders = trading_client.get_orders(order_filter)
        
        if any(o.symbol == ticker and o.created_at >= today_start for o in all_orders):
            print(f"🛡️ [SAFETY] A position deployment was already completed for {ticker} during this market session. Order blocked.")
            return state
            
        print(f"🟢 Session confirmation approved. Transmitting market entry order...")
        
        # CORRECT IMPLEMENTATION: Using the StockDataClient to stream the real-time trade price
        try:
            request_params = StockLatestTradeRequest(symbol_or_symbols=ticker)
            latest_trade = data_client.get_stock_latest_trade(request_params)
            current_price = latest_trade[ticker].price
        except Exception as e:
            print(f"❌ Pricing stream error: {e}. Aborting execution routine.")
            return state

        order_data = MarketOrderRequest(
            symbol=ticker,
            qty=1,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY
        )
        
        trading_client.submit_order(order_data)
        print(f"🚀 [SUCCESS] Base equity entry executed for 1 share of {ticker} at ${current_price:.2f}!")
        
        # Populate tracking metadata block inside our active state
        state[ticker] = {
            "highest_recorded_price": current_price,
            "sessions_held": 0,
            "atr_at_entry": atr
        }
    else:
        print(f"⏸️ [SKIP] Signal status evaluated as neutral.")
        
    return state

# 7. System Orchestration Routine
def run_bot():
    print(f"=== Starting Genius-Tier Regime-Tracking Global Portfolio Scan ===")
    
    # Initialize both distinct clients needed for full operational capacity
    trading_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True)
    data_client = StockDataClient(ALPACA_KEY, ALPACA_SECRET)
    
    state = load_portfolio_state()
    
    # Part A: Run risk auditing checks over current open positions
    state = monitor_active_portfolio_exits(trading_client, state)
    save_portfolio_state(state)
    
    # Part B: Run new session alpha scans
    for ticker in GLOBAL_TICKERS:
        try:
            state = process_scans_and_entries(ticker, trading_client, data_client, state)
            save_portfolio_state(state)
        except Exception as e:
            print(f"❌ Error processing asset tracking sequence for {ticker}: {e}. Advancing matrix...")
        
        print("⏳ Pausing 20 seconds to guarantee API safety...")
        time.sleep(20)
            
    print(f"\n=== Portfolio Scan Complete ===")

if __name__ == "__main__":
    run_bot()
