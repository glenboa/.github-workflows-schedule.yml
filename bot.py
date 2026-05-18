import os
import requests
import json
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# 1. Initialize API Keys from environment variables
FMP_KEY = os.getenv("FMP_API_KEY")
ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY")
AI_KEY = os.getenv("DEEPSEEK_API_KEY")

TICKER = "SPY"

# 2. Function to collect Market Data (Charts & News)
def get_market_data():
    # Updated to use FMP's mandatory new stable data structures
    chart_url = f"https://financialmodelingprep.com/stable/historical-price-eod/full?symbol={TICKER}&apikey={FMP_KEY}"
    news_url = f"https://financialmodelingprep.com/api/v3/stock_news?tickers={TICKER}&limit=5&apikey={FMP_KEY}"
    
    response = requests.get(chart_url).json()
    
    # Check for the correct key mapping in the new API format
    if 'historical' not in response:
        print("--- FMP API Error Response ---")
        print(response)
        print("------------------------------")
        raise KeyError("Could not find 'historical' data in FMP response. Check your API key or endpoint.")
        
    chart_data = response['historical'][:5]
    news_data = requests.get(news_url).json()
    
    return str(chart_data), str(news_data)

# 3. Function to talk to DeepSeek-R1 AI
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
        "model": "deepseek-ai/DeepSeek-R1-0528",
        "messages": [{"role": "user", "content": prompt}]
    }
    
    response = requests.post("https://api.deepinfra.com/v1/openai/chat/completions", headers=headers, json=data)
    ai_text = response.json()['choices'][0]['message']['content'].strip()
    return json.loads(ai_text)

# 4. Main Execution Engine
def run_bot():
    print("Gathering market data for SPY...")
    charts, news = get_market_data()
    
    print("Consulting DeepSeek-R1 AI model...")
    decision = ask_ai(charts, news)
    print(f"AI Decision Output: {decision}")
    
    action = decision.get("action")
    confidence = decision.get("confidence", 0.0)
    
    # Core Gatekeeper Rule
    if action == "BUY" and confidence >= 0.55:
        print(f"Confidence score of {confidence} meets execution threshold. Connecting to Alpaca Sandbox...")
        
        trading_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True)
        
        # Check if we already hold a position to manage portfolio risk
        try:
            position = trading_client.get_open_position(TICKER)
            print(f"Safety Rule: You already hold an active position in {TICKER}. Blocking duplicate order.")
            return
        except Exception:
            # An exception means no open position found, which is what we want!
            print(f"No existing position found for {TICKER}. Ready to place market order.")
            
        order_data = MarketOrderRequest(
            symbol=TICKER,
            qty=1,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY
        )
        
        trading_client.submit_order(order_data)
        print("🚀 Order successfully transmitted to Alpaca Paper Trading Platform!")
    else:
        print(f"System Action: HOLD. AI confidence score ({confidence}) did not clear execution threshold.")

if __name__ == "__main__":
    run_bot()
