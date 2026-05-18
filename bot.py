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

# 2. Automatically map the current hour to the active global session ticker
def get_current_session_ticker():
    # Gets the current time in universal UTC
    current_hour_utc = datetime.now(timezone.utc).hour
    
    print(f"System Clock Status: Active at hour {current_hour_utc} UTC")
    
    # Hour 23 UTC (11:40 PM) -> Sydney Session
    if current_hour_utc == 23:
        print("🌍 Detected: Sydney Open. Target Asset: EWA (Australia)")
        return "EWA"
    # Hour 0 UTC (12:10 AM) -> Tokyo Session
    elif current_hour_utc == 0:
        print("🌍 Detected: Tokyo Open. Target Asset: EWJ (Japan)")
        return "EWJ"
    # Hour 7 UTC (7:10 AM) -> London Session
    elif current_hour_utc == 7:
        print("🌍 Detected: London Open. Target Asset: EWU (United Kingdom)")
        return "EWU"
    # Hour 13 UTC (1:40 PM) -> New York Session
    elif current_hour_utc == 13:
        print("🌍 Detected: New York Open. Target Asset: SPY (United States)")
        return "SPY"
    # Default fallback safety valve for manual testing runs
    else:
        print("🌍 Manual/Off-hours execution detected. Defaulting to Core Asset: SPY")
        return "SPY"

TICKER = get_current_session_ticker()

# 3. Function to collect Market Data (Charts & News)
def get_market_data():
    chart_url = f"https://financialmodelingprep.com/stable/historical-price-eod/full?symbol={TICKER}&apikey={FMP_KEY}"
    news_url = f"https://financialmodelingprep.com/api/v3/stock_news?tickers={TICKER}&limit=5&apikey={FMP_KEY}"
    
    response = requests.get(chart_url).json()
    
    if isinstance(response, list):
        chart_data = response[:5]
    else:
        print("--- FMP API Error Response ---")
        print(response)
        print("------------------------------")
        raise KeyError("FMP returned an error dictionary instead of the historical price list.")
        
    news_data = requests.get(news_url).json()
    return str(chart_data), str(news_data)

# 4. Function to talk to DeepSeek-R1 AI
def ask_ai(charts, news):
    headers = {"Authorization": f"Bearer {AI_KEY}", "Content-Type": "application/json"}
    
    prompt = f"""
    Analyze this asset: {TICKER}
    Recent Candlestick Data: {charts}
    Recent News Headlines: {news}
    
    Task: Determine if the price will close higher or lower tomorrow.
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
    
    start_idx = ai_text.find('{')
    if start_idx == -1:
        print("--- Raw AI Output that failed parsing ---")
        print(ai_text)
        print("-----------------------------------------")
        raise ValueError("Could not find any opening curly bracket '{' in the AI response.")
        
    json_payload = ai_text[start_idx:]
    
    try:
        decoder = json.JSONDecoder()
        data_dict, index = decoder.raw_decode(json_payload)
        return data_dict
    except Exception as e:
        print("--- Raw AI Output that failed parsing ---")
        print(ai_text)
        print("-----------------------------------------")
        raise ValueError(f"Failed to extract valid JSON: {e}")

# 5. Main Execution Engine
def run_bot():
    print(f"Gathering market data for active ticker: {TICKER}...")
    charts, news = get_market_data()
    
    print("Consulting DeepSeek-R1 AI model...")
    decision = ask_ai(charts, news)
    print(f"AI Decision Output: {decision}")
    
    action = decision.get("action")
    confidence = decision.get("confidence", 0.0)
    
    if action == "BUY" and confidence >= 0.55:
        print(f"Confidence score of {confidence} meets execution threshold. Connecting to Alpaca Sandbox...")
        
        trading_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True)
        
        try:
            position = trading_client.get_open_position(TICKER)
            print(f"Safety Rule: You already hold an active position in {TICKER}. Blocking duplicate order.")
            return
        except Exception:
            print(f"No existing position found for {TICKER}. Ready to place market order.")
            
        order_data = MarketOrderRequest(
            symbol=TICKER,
            qty=1,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY
        )
        
        trading_client.submit_order(order_data)
        print(f"🚀 Order successfully transmitted to Alpaca Paper Trading Platform for {TICKER}!")
    else:
        print(f"System Action: HOLD. AI confidence score ({confidence}) did not clear execution threshold.")

if __name__ == "__main__":
    run_bot()
