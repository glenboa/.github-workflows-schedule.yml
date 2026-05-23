import os
import requests
import json
import time
from datetime import datetime, timezone
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# 1. System Key Configuration
ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY")

MASTER_TICKER = "BTC/USD"  
ALLOCATION_PER_TRADE = 30000.00  # Deploys $30,000 to ensure a 0.05% move equals a clean micro-profit chunk

def run_micro_yield_engine():
    print(f"=== Starting Micro-Yield Execution Engine ===")
    
    trading_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True)
    
    # 2. Risk Control Check: If a position is already open, wait for it to clear
    try:
        open_positions = trading_client.get_all_positions()
        active_symbols = [p.symbol for p in open_positions]
        if MASTER_TICKER in active_symbols:
            print(f"⏸️ Active trade already running on {MASTER_TICKER}. Standing by for target exit...")
            return
    except Exception as e:
        print(f"⚠️ Position query down: {e}")
        return

    # 3. Pull Live Price instantly via rapid ping
    try:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
        current_price = float(requests.get(url).json()['price'])
    except Exception:
        print("❌ Live price feed interrupted. Halting loop.")
        return

    calculated_qty = round(ALLOCATION_PER_TRADE / current_price, 4)
    
    # 4. MICRO-TARGET MATHEMATICS (0.05% target windows)
    # A 0.05% move on a $30,000 position captures a quick ~$15.00 return in seconds
    take_profit_price = round(current_price * 1.0005, 2)
    stop_loss_price = round(current_price * 0.9995, 2)
    
    print(f"🎯 Target Acquired: Live BTC at ${current_price:.2f}")
    print(f"📊 Order Bracket -> Take Profit: ${take_profit_price:.2f} | Stop Loss: ${stop_loss_price:.2f}")
    
    # 5. Execute Bracket Order immediately
    order_data = MarketOrderRequest(
        symbol=MASTER_TICKER,
        qty=calculated_qty,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        take_profit=TakeProfitRequest(limit_price=take_profit_price),
        stop_loss=StopLossRequest(stop_price=stop_loss_price)
    )
    
    try:
        print(f"🟢 [FIRING] Sending high-velocity order for {calculated_qty} BTC units...")
        trading_client.submit_order(order_data)
        print("🚀 [SUCCESS] Position established with hardcoded exit brackets deployed.")
    except Exception as e:
        print(f"❌ Order execution rejected: {e}")

    print("=== Micro-Yield Engine Loop Complete ===")

if __name__ == "__main__":
    run_micro_yield_engine()
