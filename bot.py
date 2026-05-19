import os
import requests
import json
import re
import time
from datetime import datetime, timezone, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus

# 1. Initialize API Keys from environment variables
FMP_KEY = os.getenv("FMP_API_KEY")
ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY")
AI_KEY = os.getenv("DEEPSEEK_API_KEY")

GLOBAL_TICKERS = ["SPY", "NVDA", "AAPL", "MSFT"]

# 2. Function to collect Market Data
def get_market_data(ticker):
    today = datetime.now(timezone.utc)
    start_date = (today - timedelta(days=10)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")
    
    chart_url = "https://financialmodelingprep.com/stable/historical-price-eod/full"
    chart_params = {
        "symbol": ticker,
        "from": start_date,
        "to": end_date,
        "apikey": FMP_KEY
    }
    
    response = requests.get(chart_url, params=chart_params)
    chart_response = response.json()
    
    if isinstance(chart_response, list):
        chart_data = chart_response[:5]
    else:
        print(f"--- FMP API Error Response for {ticker} ---")
        print(chart_response)
        print("------------------------------------------")
        raise KeyError(f"FMP Stable API returned an error structure for {ticker}.")
        
    calendar_url = "https://financialmodelingprep.com/stable/economic-calendar"
    calendar_params = {
        "from": end_date,
        "to": end_date,
        "apikey": FMP_KEY
    }
    
    calendar_events = []
    try:
        calendar_response = requests.get(calendar_url, params=calendar_params).json()
        if isinstance(calendar_response, list):
            calendar_events = [
                {
                    "event": event.get("event"),
                    "country": event.get("country"),
                    "actual": event.get("actual"),
                    "estimate": event.get("estimate"),
                    "previous": event.get("previous"),
                    "impact": event.get("impact")
                }
                for event in calendar_response if event.get("impact") in ["Medium", "High"]
            ]
    except Exception as e:
        print(f"⚠️ Warning: Could not parse economic calendar data: {e}")

    return str(chart_data), str(calendar_events)

# 3. Function to talk to DeepSeek-R1 AI
def ask_ai(ticker, charts, calendar):
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
        print("--- DeepInfra API Error Response ---")
        print(response)
        print("------------------------------------")
        raise KeyError("Could not find 'choices' in AI response.")
        
    ai_text = response['choices'][0]['message']['content'].strip()
    
    json_blocks = re.findall(r"\{.*?\}", ai_text, re.DOTALL)
    if not json_blocks:
        print("--- Raw AI Output that failed parsing ---")
        print(ai_text)
        print("-----------------------------------------")
        raise ValueError("Could not find any JSON structural blocks in the AI response.")
        
    json_payload = json_blocks[-1]
    
    try:
        return json.loads(json_payload)
    except Exception as e:
        print("--- Text segment that failed final parsing ---")
        print(json_payload)
        print("----------------------------------------------")
        raise ValueError(f"JSON decoder failed to handle selected block: {e}")

# 4. Core Scanning Engine for a single ticker
def process_ticker(ticker, trading_client):
    print(f"\n🔄 [SCANNING] Fetching technical data & economic calendar for {ticker}...")
    charts, calendar = get_market_data(ticker)
    
    print(f"🧠 [ANALYZING] Consulting DeepSeek-R1 Macro Brain for {ticker}...")
    decision = ask_ai(ticker, charts, calendar)
    print(f"📊 [AI OUTPUT] {ticker} Decision: {decision}")
    
    action = decision.get("action")
    confidence = decision.get("confidence", 0.0)
    
    # FOR THIS MANUAL TEST: We accept BUY or HOLD to force trades through and see the new brackets work
    if action in ["BUY", "HOLD"]:
        print(f"🎯 [EXECUTE] Active mode triggered! Checking session order history...")
        
        # HIGH ACTIVITY FIX: Check if we already placed an order TODAY, instead of blocking wholesale open positions
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        order_filter = GetOrdersRequest(
            status=QueryOrderStatus.ALL,
            side=OrderSide.BUY,
            nested=False
        )
        
        all_orders = trading_client.get_orders(order_filter)
        duplicate_found = False
        
        for order in all_orders:
            if order.symbol == ticker and order.created_at >= today_start:
                duplicate_found = True
                break
                
        if duplicate_found:
            print(f"🛡️ [SAFETY] You already fired a trade for {ticker} during this market session. Skipping to protect capital.")
            return
            
        print(f"🟢 No recent session orders for {ticker}. Fetching execution price...")
        
        try:
            latest_trade = trading_client.get_latest_trade(ticker)
            current_price = latest_trade.price
            print(f"💵 Current Market Price for {ticker}: ${current_price:.2f}")
        except Exception as e:
            print(f"❌ Failed to fetch current price from Alpaca: {e}. Skipping order execution.")
            return

        # ASSET-SPECIFIC VOLATILITY BRACKETS (Paul Tudor Jones 3:1 Ratio)
        if ticker in ["SPY"]:
            sl_percent = 0.015  # 1.5% Stop Loss
            tp_percent = 0.045  # 4.5% Take Profit
        else:
            sl_percent = 0.025  # 2.5% Stop Loss
            tp_percent = 0.075  # 7.5% Take Profit

        stop_loss_price = round(current_price * (1.0 - sl_percent), 2)
        take_profit_price = round(current_price * (1.0 + tp_percent), 2)
        
        print(f"🛡️ Risk Setup -> Stop Loss: ${stop_loss_price:.2f} | Take Profit: ${take_profit_price:.2f}")
            
        order_data = MarketOrderRequest(
            symbol=ticker,
            qty=1,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class="bracket",
            take_profit={"limit_price": take_profit_price},
            stop_loss={"stop_price": stop_loss_price}
        )
        
        trading_client.submit_order(order_data)
        print(f"🚀 [SUCCESS] Server-Side Bracket Order transmitted to Alpaca for {ticker}!")
    else:
        print(f"⏸️ [SKIP] Asset skipped.")

# 5. Main Loop Execution
def run_bot():
    print(f"=== Starting Macro-Driven Global Session Portfolio Scan ===")
    
    trading_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True)
    
    for ticker in GLOBAL_TICKERS:
        try:
            process_ticker(ticker, trading_client)
        except Exception as e:
            print(f"❌ Error processing {ticker}: {e}. Skipping to next asset...")
        
        print("⏳ Pausing 20 seconds to guarantee API safety...")
        time.sleep(20)
            
    print(f"\n=== Portfolio Scan Complete ===")

if __name__ == "__main__":
    run_bot()
