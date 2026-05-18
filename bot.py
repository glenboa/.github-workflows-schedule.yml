import os
import requests
import json
import re
import time
from datetime import datetime, timezone, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# 1. Initialize API Keys from environment variables
FMP_KEY = os.getenv("FMP_API_KEY")
ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY")
AI_KEY = os.getenv("DEEPSEEK_API_KEY")

GLOBAL_TICKERS = ["SPY", "QQQ", "EWJ", "EWU", "GLD"]

# 2. Bulk Market Fetcher (Only calls the API ONCE for the whole portfolio)
def fetch_bulk_market_data():
    print("📥 [DATA] Fetching bulk market data for all assets simultaneously...")
    today = datetime.now(timezone.utc)
    start_date = (today - timedelta(days=10)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")
    
    # Convert list to comma-separated string: "SPY,QQQ,EWJ,EWU,GLD"
    ticker_string = ",".join(GLOBAL_TICKERS)
    
    chart_url = f"https://financialmodelingprep.com/stable/historical-price-eod/full?symbol={ticker_string}&from={start_date}&to={end_date}&apikey={FMP_KEY}"
    
    bulk_charts = {}
    for attempt in range(3):
        try:
            response = requests.get(chart_url)
            chart_response = response.json()
            
            if isinstance(chart_response, list):
                # Organize the bulk list into a neat dictionary grouped by ticker symbol
                for item in chart_response:
                    sym = item.get("symbol")
                    if sym:
                        if sym not in bulk_charts:
                            bulk_charts[sym] = []
                        if len(bulk_charts[sym]) < 5:
                            bulk_charts[sym].append(item)
                break
        except Exception:
            pass
        time.sleep(3)
        
    if not bulk_charts:
        raise KeyError("FMP Bulk API failed to return data. The free tier limit might be exhausted for the hour.")
        
    # Fetch Today's Global Economic Events Calendar (Only 1 call needed)
    today_date = today.strftime("%Y-%m-%d")
    calendar_url = f"https://financialmodelingprep.com/api/v3/economic_calendar?from={today_date}&to={today_date}&apikey={FMP_KEY}"
    
    calendar_events = []
    try:
        calendar_response = requests.get(calendar_url).json()
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

    return bulk_charts, calendar_events

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
def process_ticker(ticker, charts, calendar, trading_client):
    print(f"\n🧠 [ANALYZING] Consulting DeepSeek-R1 Macro Brain for {ticker}...")
    decision = ask_ai(ticker, charts, calendar)
    print(f"📊 [AI OUTPUT] {ticker} Decision: {decision}")
    
    action = decision.get("action")
    confidence = decision.get("confidence", 0.0)
    
    if action in ["BUY", "HOLD"]:
        print(f"🎯 [EXECUTE] Confidence ({confidence}) clears threshold. Checking open positions...")
        
        try:
            position = trading_client.get_open_position(ticker)
            print(f"🛡️ [SAFETY] Active position in {ticker} detected. Order blocked to control risk.")
            return
        except Exception:
            print(f"🟢 No open positions for {ticker}. Submitting order...")
            
        order_data = MarketOrderRequest(
            symbol=ticker,
            qty=1,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY
        )
        
        trading_client.submit_order(order_data)
        print(f"🚀 [SUCCESS] Order successfully transmitted to Alpaca for 1 share of {ticker}!")
    else:
        print(f"⏸️ [HOLD] AI recommendation is HOLD or confidence ({confidence}) is too low.")

# 5. Main Loop Execution
def run_bot():
    print(f"=== Starting Bulk Macro-Driven Global Session Portfolio Scan ===")
    
    trading_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True)
    
    try:
        bulk_charts, calendar_events = fetch_bulk_market_data()
    except Exception as e:
        print(f"❌ Critical Error loading market data: {e}")
        return
    
    for ticker in GLOBAL_TICKERS:
        ticker_charts = bulk_charts.get(ticker, [])
        if not ticker_charts:
            print(f"⚠️ Skipping {ticker}: No technical chart data returned in bulk package.")
            continue
            
        try:
            process_ticker(ticker, str(ticker_charts), str(calendar_events), trading_client)
        except Exception as e:
            print(f"❌ Error processing {ticker}: {e}. Skipping to next asset...")
            
    print(f"\n=== Portfolio Scan Complete ===")

if __name__ == "__main__":
    run_bot()
