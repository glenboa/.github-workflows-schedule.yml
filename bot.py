import os
import requests
import json
import re
import time
from datetime import datetime, timezone, timedelta
from alpaca.trading.client import TradingClient
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoLatestTradeRequest
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# 1. System Configuration
FMP_KEY = os.getenv("FMP_API_KEY")
ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY")
AI_KEY = os.getenv("DEEPSEEK_API_KEY")

# LASER FOCUS TARGET: The #1 absolute volatility asset on the platform
MASTER_TICKER = "BTC/USD"  
STATE_FILE = "portfolio_state.json"
JOURNAL_FILE = "trade_journal.json"  # THE BOT'S ACTIVE DATABASE LENS
ALLOCATION_PER_TRADE = 15000.00      # Deploys a robust $15,000 block per scalp to capture moves

# 2. Local Database State Handlers
def load_json_file(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f: return json.load(f)
        except Exception: return {}
    return {}

def save_json_file(filename, data):
    try:
        with open(filename, "w") as f: json.dump(data, f, indent=4)
    except Exception as e: print(f"❌ Storage error: {e}")

# 3. Post-Mortem Logging Engine: Writing Down Mistakes & Successes
def log_trade_to_journal(entry_price, exit_price, outcome, loops_active, confidence):
    journal = load_json_file(JOURNAL_FILE)
    if "history" not in journal:
        journal["history"] = []
        
    profit_loss_pct = round(((exit_price - entry_price) / entry_price) * 100, 2)
    if outcome == "LOSS":
        profit_loss_pct = -abs(profit_loss_pct)

    log_entry = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "asset": MASTER_TICKER,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "outcome": outcome,
        "profit_loss_pct": profit_loss_pct,
        "loops_held": loops_active,
        "ai_confidence_at_entry": confidence
    }
    
    journal["history"].append(log_entry)
    # Save the last 20 clean logs so the neural network context doesn't get flooded
    journal["history"] = journal["history"][-20:]
    save_json_file(JOURNAL_FILE, journal)
    print(f"🧠 [MEMORY] Logged {MASTER_TICKER} trade to feedback ledger. PnL: {profit_loss_pct}%.")

# 4. Volatility Calculation Engine (ATR)
def calculate_btc_atr_and_data():
    today = datetime.now(timezone.utc)
    start_date = (today - timedelta(days=15)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")
    
    chart_url = "https://financialmodelingprep.com/stable/historical-price-eod/full"
    response = requests.get(chart_url, params={"symbol": "BTC", "from": start_date, "to": end_date, "apikey": FMP_KEY}).json()
    
    if not isinstance(response, list) or len(response) < 6:
        raise KeyError("Insufficient historical framework data parsed for BTC.")
        
    chart_data = response[:5]
    true_ranges = []
    for i in range(5):
        high = float(response[i].get("high", 0))
        low = float(response[i].get("low", 0))
        close_prev = float(response[i+1].get("close", 0)) if i+1 < len(response) else low
        tr = max(high - low, abs(high - close_prev), abs(low - close_prev))
        true_ranges.append(tr)
        
    return chart_data, (sum(true_ranges) / len(true_ranges))

# 5. Neural Communication Gate with Self-Correcting Feedback Context
def ask_deepseek_with_memory(charts, historical_history):
    headers = {"Authorization": f"Bearer {AI_KEY}", "Content-Type": "application/json"}
    
    prompt = f"""
    Analyze the absolute top volatility currency asset: {MASTER_TICKER}
    Recent Candlestick Data: {charts}
    
    --- YOUR HISTORICAL TRADING EXPERIENCES (LEARNING LEDGER) ---
    Analyze your past trade records provided below. Study the exact entry patterns that resulted in a 'LOSS' versus those that yielded a 'WIN'.
    If a specific style of breakout, chart setup, or low-confidence trade lost money recently, modify your strategy instantly to avoid replicating the exact mistake:
    {json.dumps(historical_history, indent=2)}
    --------------------------------------------------------------
    
    Task: Combine your historical tracking memory with current market technical structures to dictate if a highly precise momentum scalp buy is viable right now.
    You must output exactly valid JSON format only, with no other conversational prose.
    Format: {{"action": "BUY", "confidence": 0.74}} or {{"action": "HOLD", "confidence": 0.00}}
    """
    
    data = {
        "model": "deepseek-ai/DeepSeek-R1",
        "messages": [{"role": "user", "content": prompt}]
    }
    
    response = requests.post("https://api.deepinfra.com/v1/openai/chat/completions", headers=headers, json=data).json()
    ai_text = response['choices'][0]['message']['content'].strip()
    json_blocks = re.findall(r"\{.*?\}", ai_text, re.DOTALL)
    return json.loads(json_blocks[-1])

# 6. Active Execution Risk & Tight Trailing Stop Manager
def monitor_active_portfolio_exits(trading_client, state):
    print("\n🔍 [RISK MONITOR] Auditing active Bitcoin exposure boundaries...")
    try:
        open_positions = trading_client.get_all_positions()
    except Exception:
        return state

    active_symbols = [p.symbol for p in open_positions]
    state = {t: data for t, data in state.items() if t in active_symbols}

    for position in open_positions:
        ticker = position.symbol
        if ticker != MASTER_TICKER: continue
        
        current_price = float(position.current_price)
        state[ticker]["sessions_held"] += 1
        
        if current_price > state[ticker]["highest_recorded_price"]:
            state[ticker]["highest_recorded_price"] = current_price
            
        highest_tracked = state[ticker]["highest_recorded_price"]
        saved_atr = state[ticker]["atr_at_entry"]
        
        # Hyper-Scalper Trailing Floor: Tight 1.2x ATR trailing below the peak to tightly seal profits
        trailing_stop_floor = round(highest_tracked - (1.2 * saved_atr), 2)
        print(f"📊 {MASTER_TICKER} -> Price: ${current_price:.2f} | Floor: ${trailing_stop_floor:.2f} | Loops Active: {state[ticker]['sessions_held']}/5")

        # Exit Rule A: Floor Violated
        if current_price <= trailing_stop_floor:
            print(f"🚨 [VOLATILITY TRAIL BREAK] Fell below trailing stop threshold. Liquidating...")
            trading_client.close_position(MASTER_TICKER)
            log_trade_to_journal(state[ticker]["entry_price"], current_price, "LOSS", state[ticker]["sessions_held"], state[ticker]["confidence_at_entry"])
            del state[ticker]
            continue

        # Exit Rule B: Velocity Time Out (5 script loops = 25 minutes max duration)
        if state[ticker]["sessions_held"] >= 5:
            print(f"⏳ [VELOCITY STAGNATION] Position held for 25 minutes. Liquidating to maintain agility...")
            trading_client.close_position(MASTER_TICKER)
            outcome = "WIN" if current_price >= state[ticker]["entry_price"] else "LOSS"
            log_trade_to_journal(state[ticker]["entry_price"], current_price, outcome, state[ticker]["sessions_held"], state[ticker]["confidence_at_entry"])
            del state[ticker]
            continue
            
    return state

# 7. Orchestration Routine
def run_master_engine():
    print(f"=== Starting Single-Pair Learning Machine on {MASTER_TICKER} ===")
    
    trading_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True)
    data_client = CryptoHistoricalDataClient() # Dedicated SDK module for clean pricing execution
    
    state = load_json_file(STATE_FILE)
    journal = load_json_file(JOURNAL_FILE)
    
    # Audit current positions first
    state = monitor_active_portfolio_exits(trading_client, state)
    save_json_file(STATE_FILE, state)
    
    if MASTER_TICKER in state:
        print(f"🛡️ Position already running on {MASTER_TICKER}. Halting further entry execution.")
        return

    # Run Analysis using memory logs
    chart_data, atr = calculate_btc_atr_and_data()
    decision = ask_deepseek_with_memory(str(chart_data), journal.get("history", []))
    print(f"📊 [AI SYSTEM FORECAST] DeepSeek Core Output: {decision}")
    
    if decision.get("action") == "BUY":
        try:
            request_params = CryptoLatestTradeRequest(symbol_or_symbols=MASTER_TICKER)
            latest_trade = data_client.get_crypto_latest_trade(request_params)
            current_price = float(latest_trade[MASTER_TICKER].price)
        except Exception:
            current_price = float(chart_data[0].get("close"))

        calculated_qty = round(ALLOCATION_PER_TRADE / current_price, 4)
        print(f"🟢 [SUBMITTING FILL] Deploying ${ALLOCATION_PER_TRADE} buying power -> Buying {calculated_qty} units of BTC...")
        
        order_data = MarketOrderRequest(
            symbol=MASTER_TICKER,
            qty=calculated_qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY
        )
        
        try:
            trading_client.submit_order(order_data)
            state[MASTER_TICKER] = {
                "entry_price": current_price,
                "highest_recorded_price": current_price,
                "sessions_held": 0,
                "atr_at_entry": atr,
                "confidence_at_entry": decision.get("confidence", 0.0)
            }
            save_json_file(STATE_FILE, state)
            print("🚀 [SUCCESS] Master Position Established.")
        except Exception as e:
            print(f"❌ Alpaca execution rejected: {e}")
            
    print("=== System Loop Complete ===")

if __name__ == "__main__":
    run_master_engine()
