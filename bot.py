import os
import json
import time
from datetime import datetime, timezone
from alpaca.trading.client import TradingClient
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoLatestTradeRequest
from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# 1. System Key Configuration
ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY")

MASTER_TICKER = "BTC/USD"  
ALLOCATION_PER_TRADE = 30000.00  # Deploys $30,000 buying power per bullet to sweep up small moves

def run_micro_yield_engine():
    print(f"=== Starting Micro-Yield Execution Engine ===")
    
    trading_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True)
    data_client = CryptoHistoricalDataClient() # Self-contained internal Alpaca pricing module
    
    # 2. Open Risk Mitigation Gate
    try:
        open_positions = trading_client.get_all_positions()
        active_symbols = [p.symbol for p in open_positions]
        if MASTER_TICKER in active_symbols:
            print(f"⏸️ Active trade already running on {MASTER_TICKER}. Standing by for target bracket exit...")
            return
    except Exception as e:
        print(f"⚠️ Position query down: {e}")
        return

    # 3. Pull Live Price natively from Alpaca's data network
    try:
        request_params = CryptoLatestTradeRequest(symbol_or_symbols=MASTER_TICKER)
        latest_trade = data_client.get_crypto_latest_trade(request_params)
        current_price = float(latest_trade[MASTER_TICKER].price)
    except Exception as e:
        print(f"❌ Alpaca live data stream interrupted: {e}. Halting loop.")
        return

    calculated_qty = round(ALLOCATION_PER_TRADE / current_price, 4)
    
    # 4. MICRO-TARGET MATHEMATICS (0.05% Symmetric Windows)
    # At a $30,000 position size, a 0.05% tick captures a quick ~$15.00 cash return instantly
    take_profit_price = round(current_price * 1.0005, 2)
    stop_loss_price = round(current_price * 0.9995, 2)
    
    print(f"🎯 Target Acquired: Live BTC at ${current_price:.2f}")
    print(f"📊 Order Bracket -> Take Profit: ${take_profit_price:.2f} | Stop Loss: ${stop_loss_price:.2f}")
    
    # 5. Execute Multi-Bracket Order structure instantly
    order_data = MarketOrderRequest(
        symbol=MASTER_TICKER,
        qty=calculated_qty,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        take_profit=TakeProfitRequest(limit_price=take_profit_price),
        stop_loss=StopLossRequest(stop_price=stop_loss_price)
    )
    
    try:
        print(f"🟢 [FIRING SNIPER] Sending high-velocity bracket order for {calculated_qty} BTC units...")
        trading_client.submit_order(order_data)
        print("🚀 [SUCCESS] Position established with hardcoded exit brackets deployed.")
    except Exception as e:
        print(f"❌ Alpaca execution rejected: {e}")

    print("=== Micro-Yield Engine Loop Complete ===")

if __name__ == "__main__":
    run_micro_yield_engine()
