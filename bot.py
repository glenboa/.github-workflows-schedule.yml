import os
import requests
import json
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# Initialize API Keys from environment variables
FMP_KEY = os.getenv("FMP_API_KEY")
ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY")
AI_KEY = os.getenv("DEEPSEEK_API_KEY")

TICKER = "SPY" 

def get_market_data():
    chart_url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{TICKER}?apikey={FMP_KEY}"
    chart_data = requests.get(chart_url).json()['historical'][:5] 
    
    news_url = f"https://financialmodelingprep.com/api/v3/stock_news?tickers={TICKER}&limit=5&apikey={FMP_KEY}"
    news_data = requests.get(news_url).json()
    
    return str(chart_data), str(news_data)

def ask_ai(charts, news):
    headers = {"Authorization": f"Bearer {AI_KEY}", "Content-Type": "application/json"}
    
    prompt = f"""
    Analyze this asset: {TICKER}
    Recent Candlestick Data: {charts}
    Recent News Headlines: {news}
    
    Task: Determine if the price will close higher or lower tomorrow.
    You must output exactly valid JSON format only, with no other conversational text.
    Format: {{"action": "BUY", "confidence": 0.58}} or {{"action": "HOLD", "confidence": 0.00}}
    """
    
    data = {
        "model": "deepseek-ai/DeepSeek-R1-0528",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1
    }
    
    response = requests.post("https://api.deepinfra.com/v1/openai/chat/completions", headers=headers, json=data)
    ai_output = response.json()['choices'][0]['message']['content']
    
    if "</thought>" in ai_output:
        ai_output = ai_output.split("</thought>")[1]
        
    return json.loads(ai_output.strip())

def execute_trade(decision):
    trading_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True)
    
    if decision['action'] == "BUY" and decision['confidence'] >= 0.55:
        positions = trading_client.get_all_positions()
        already_owned = any(p.symbol == TICKER for p in positions)
        
        if not already_owned:
            order_data = MarketOrderRequest(
                symbol=TICKER,
                qty=1,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY
            )
            trading_client.submit_order(order_data=order_data)
            print(f"Successfully bought 1 share of {TICKER}")
    else:
        print("AI target confidence not met or action is HOLD. No trade executed.")

if __name__ == "__main__":
    charts, news = get_market_data()
    decision = ask_ai(charts, news)
    execute_trade(decision)