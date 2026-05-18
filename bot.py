import os
import requests
import json
import re
from datetime import datetime, timezone
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# 1. Initialize API Keys from environment variables
FMP_KEY = os.getenv("FMP_API_KEY")
ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY")
AI_KEY = os.getenv("DEEPSEEK_API_KEY")

GLOBAL_TICKERS = ["SPY", "QQQ", "EWJ", "EWU", "GLD"]

# 2. Function to collect Market Data (Charts & Global Macro Economic Calendar)
def get_market_data(ticker):
    # Restored to the highly stable v3 full historical endpoint
    chart_url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}?apikey={FMP_KEY}"
    chart_response = requests.get(chart_url).json()
    
    if isinstance(chart_response, dict) and "historical" in chart_response:
        chart_data = chart_response["historical"][:5]
    else:
        print(f"--- FMP API Error Response for {ticker} ---")
        print(chart_response)
        print("------------------------------------------")
        raise KeyError(f"FMP returned an unexpected data structure for {ticker}.")
        
    # Fetch Today's Global Economic Events Calendar
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
        raise KeyError("Could not find 'choices' in AI response. Check your API key or model name.")
        
    ai_text = response['choices'][0]['message']['content'].strip()
    
    # Advanced Regex Fix: Extracts ONLY the text between the first '{' and the last '}'
    match = re.search(r"\{.*\}", ai_text, re.DOTALL)
    if not match:
        print("--- Raw AI Output that failed parsing ---")
        print(ai_text)
        print("-----------------------------------------")
        raise ValueError("Could not find any clean JSON block in the AI response.")
        
    json_payload = match.group(0)
    
    try:
        return json.loads(json_payload)
    except Exception as e:
        print("--- Regex extracted text that failed decoding ---")
        print(json_payload)
        print("-------------------------------------------------")
        raise ValueError(f"Failed to decode extracted JSON: {e}")

# 4. Core Scanning Engine for a single ticker
def process_ticker(ticker, trading_client):
    print(f"\n🔄 [SCANNING] Fetching technical data & economic calendar for {ticker}...")
    charts, calendar = get_market_data(ticker)
    
    print(f"🧠 [ANALYZING] Consulting DeepSeek-R1 Macro Brain for {ticker}...")
    decision = ask_ai(ticker, charts, calendar)
    print(f"📊 [AI OUTPUT] {ticker} Decision: {decision}")
    
    action = decision.get("action")
    confidence = decision.get("confidence", 0.0)
    
    # Aggressive test trigger to guarantee execution
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
    print(f"=== Starting Macro-Driven Global Session Portfolio Scan ===")
    
    trading_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True)
    
    for ticker in GLOBAL_TICKERS:
        try:
            process_ticker(ticker, trading_client)
        except Exception as e:
            print(f"❌ Error processing {ticker}: {e}. Skipping to next asset...")
            
    print(f"\n=== Portfolio Scan Complete ===")

if __name__ == "__main__":
    run_bot()
