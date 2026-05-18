import os
import requests
import json
import re
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# 1. Initialize API Keys from environment variables
FMP_KEY = os.getenv("FMP_API_KEY")
ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY")
AI_KEY = os.getenv("DEEPSEEK_API_KEY")

# The Core 5 Global Most-Traded ETFs
GLOBAL_TICKERS = ["SPY", "QQQ", "EWJ", "EWU", "EWA"]

# 2. Function to collect Market Data (Charts & News)
def get_market_data(ticker):
    chart_url = f"https://financialmodelingprep.com/stable/historical-price-eod/full?symbol={ticker}&apikey={FMP_KEY}"
    news_url = f"https://financialmodelingprep.com/api/v3/stock_news?tickers={ticker}&limit=5&apikey={FMP_KEY}"
    
    response = requests.get(chart_url).json()
    
    if isinstance(response, list):
        chart_data = response[:5]
    else:
        print(f"--- FMP API Error Response for {ticker} ---")
        print(response)
        print("------------------------------------------")
        raise KeyError(f"FMP returned an error dictionary instead of the historical price list for {ticker}.")
        
    news_data = requests.get(news_url).json()
    return str(chart_data), str(news_data)

# 3. Function to talk to DeepSeek-R1 AI
def ask_ai(ticker, charts, news):
    headers = {"Authorization": f"Bearer {AI_KEY}", "Content-Type": "application/json"}
    
    prompt = f"""
    Analyze this asset: {ticker}
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

# 4. Core Scanning Engine for a single ticker
def process_ticker(ticker, trading_client):
    print(f"\n🔄 [SCANNING] Fetching market data for {ticker}...")
    charts, news = get_market_data(ticker)
    
    print(f"🧠 [ANALYZING] Consulting DeepSeek-R1 for {ticker}...")
    decision = ask_ai(ticker, charts, news)
    print(f"📊 [AI OUTPUT] {ticker} Decision: {decision}")
    
    action = decision.get("action")
    confidence = decision.get("confidence", 0.0)
    
    if action == "BUY" and confidence >= 0.55:
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
    print(f"=== Starting Global Session Portfolio Scan ===")
    
    # Initialize trading client once for the entire run
    trading_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True)
    
    # Loop seamlessly through all five global assets
    for ticker in GLOBAL_TICKERS:
        try:
            process_ticker(ticker, trading_client)
        except Exception as e:
            print(f"❌ Error processing {ticker}: {e}. Skipping to next asset...")
            
    print(f"\n=== Portfolio Scan Complete ===")

if __name__ == "__main__":
    run_bot()
