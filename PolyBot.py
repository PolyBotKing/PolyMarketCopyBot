import asyncio
import json
import logging
import sys
import websockets
import time
import requests
from decimal import Decimal, ROUND_DOWN
from datetime import datetime
from collections import deque
from concurrent.futures import ThreadPoolExecutor

# Only for Notebook environment (optional if running locally)
import nest_asyncio
nest_asyncio.apply()

# ================= ⚡️ FREE TRACKER CONFIG ⚡️ =================

# 1. TARGET TO TRACK
TARGET_WALLET = "0x63ce342161250d705dc0b16df89036c8e5f9ba9a".lower()
TARGET_ESTIMATED_BANKROLL = 30000.0

# 2. SIMULATION SETTINGS
MY_BANKROLL = 1000.0    
USE_RATIO = True
MY_FIXED_BET_SIZE = 10.0
COPY_SELLS = True       

# 3. SAFETY SIMULATION
MAX_SLIPPAGE = 10.0     
MAX_PRICE_CAP = 0.99
MIN_PRICE_CAP = 0.01    

POLL_INTERVAL_SECONDS = 0.5 
ORDERBOOK_EXPIRY_SECONDS = 900 
TEST_ON_STARTUP = True  # Set to True to print a test trade immediately on launch

# ==========================================================

logging.basicConfig(
    format='%(asctime)s | %(message)s',
    level=logging.INFO,
    datefmt='%H:%M:%S',
    stream=sys.stdout,
    force=True
)
logger = logging.getLogger("FreeTracker")

class PolymarketTracker:
    def __init__(self):
        self.fills_log = [] 
        self.trade_timestamps = deque()
        self.session = requests.Session()
        self.seen_trade_hashes = set()
        self.last_trade_timestamp = 0
        
        # Async executor for non-blocking HTTP
        self.executor = ThreadPoolExecutor(max_workers=5)
        
        self.orderbooks = {} 
        self.subscribed_markets = {} 
        self.pending_subscriptions = asyncio.Queue()
        self.orderbook_ws = None

        self.ratio = (MY_BANKROLL / TARGET_ESTIMATED_BANKROLL) if TARGET_ESTIMATED_BANKROLL > 0 else 0.01
        
        logger.info(f"👀 TRACKER INITIALIZED")
        logger.info(f"⚖️  Simulated Ratio: {self.ratio*100:.4f}%")

    # --- ASYNC HTTP WRAPPER ---
    async def fetch_url(self, url, params=None):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, lambda: self.session.get(url, params=params, timeout=3))

    # --- PnL CALCULATION (SIMULATED) ---
    async def calculate_session_pnl(self):
        total_invested = 0.0
        total_value = 0.0
        
        # Non-blocking update of books
        assets_to_update = set(t['asset'] for t in self.fills_log)
        for asset in assets_to_update:
            try:
                resp = await self.fetch_url("https://clob.polymarket.com/book", params={"token_id": asset})
                if resp.status_code == 200:
                    book = resp.json()
                    self.orderbooks[asset] = {
                        'asks': book.get('asks', []), 'bids': book.get('bids', []), 'timestamp': time.time()
                    }
            except:
                pass

        print("\n" + "="*90)
        print(f"💰 SIMULATED PnL REPORT ({len(self.fills_log)} Tracked Trades)")
        print(f"{'TIME':<9} {'SIDE':<4} {'ENTRY':<8} {'BID':<8} {'ASK':<8} {'MID':<8} {'PnL'}")
        print("-" * 90)
        
        for trade in self.fills_log:
            asset = trade['asset']
            shares = trade['shares']
            entry = trade['price']
            side = trade['side']
            
            best_bid = 0.0
            best_ask = 0.0
            
            if asset in self.orderbooks:
                book = self.orderbooks[asset]
                bids = book.get('bids', [])[:]
                bids.sort(key=lambda x: float(x['price']), reverse=True)
                if bids: best_bid = float(bids[0]['price'])
                asks = book.get('asks', [])[:]
                asks.sort(key=lambda x: float(x['price']))
                if asks: best_ask = float(asks[0]['price'])

            mid_price = entry
            if best_bid > 0 and best_ask > 0:
                mid_price = (best_bid + best_ask) / 2
            elif best_ask > 0:
                mid_price = best_ask
            elif best_bid > 0:
                mid_price = best_bid

            # --- VALUATION ---
            if side == 'BUY':
                curr_price = best_bid if best_bid > 0 else (best_ask * 0.9)
                pnl = (curr_price - entry) * shares
                total_invested += (shares * entry)
                total_value += (shares * curr_price)
            else:
                curr_price = best_ask if best_ask > 0 else (best_bid * 1.1)
                pnl = (entry - curr_price) * shares
                total_invested += (shares * entry)
                total_value += (shares * entry) + pnl 
            
            print(f"{trade['time']:<9} {side:<4} ${entry:<7.3f} ${best_bid:<7.3f} ${best_ask:<7.3f} ${mid_price:<7.3f} ${pnl:+.2f}")

        print("-" * 90)
        print(f"💵 SIMULATED INVESTED: ${total_invested:.2f}")
        print(f"💎 SIMULATED VALUE:    ${total_value:.2f}")
        print(f"🚀 SIMULATED PnL:      ${(total_value - total_invested):+.2f}")
        print("="*90 + "\n")

    # --- ORDERBOOK CACHE ---
    def get_cached_orderbook(self, token_id):
        if token_id in self.orderbooks:
            cached = self.orderbooks[token_id]
            if time.time() - cached.get('timestamp', 0) < 5:
                return cached
        return None

    async def check_liquidity_and_fill(self, token_id, limit_price, needed_shares, side, force_market_price=False):
        cached = self.get_cached_orderbook(token_id)
        source = "CACHE"
        
        if not cached:
            try:
                source = "REST"
                resp = await self.fetch_url("https://clob.polymarket.com/book", params={"token_id": token_id})
                if resp.status_code == 200:
                    book = resp.json()
                    self.orderbooks[token_id] = {
                        'asks': book.get('asks', []), 'bids': book.get('bids', []), 'timestamp': time.time()
                    }
                    cached = self.orderbooks[token_id]
            except Exception:
                pass

        if not cached: return 0, 0, "NONE"

        if side == 'BUY':
            book_levels = cached.get('asks', [])[:] 
            book_levels.sort(key=lambda x: float(x['price']))
        else:
            book_levels = cached.get('bids', [])[:] 
            book_levels.sort(key=lambda x: float(x['price']), reverse=True)

        if not book_levels:
            return 0, 0, "EMPTY_BOOK"

        filled_shares = 0.0
        total_cost = 0.0
        remaining = needed_shares

        for level in book_levels:
            price = float(level['price'])
            size = float(level['size'])
            
            if not force_market_price:
                if side == 'BUY' and price > limit_price: break
                if side == 'SELL' and price < limit_price: break
            
            take = min(remaining, size)
            filled_shares += take
            total_cost += (take * price)
            remaining -= take
            if remaining <= 0: break
            
        avg_price = (total_cost / filled_shares) if filled_shares > 0 else 0
        return filled_shares, avg_price, source

    # --- SIMULATED EXECUTION ---
    async def execute_trade(self, trade_data, is_test=False):
        side = trade_data.get('side', '').upper()
        price = float(trade_data.get('price', 0))
        size = float(trade_data.get('size', 0))
        asset_id = trade_data.get('asset')
        title = trade_data.get('title', 'Unknown')[:40]
        outcome = trade_data.get('outcome', '?')

        prefix = "🧪 TEST" if is_test else "🔔 TRACKER SIGNAL"
        logger.info("-" * 60)
        logger.info(f"{prefix}: {side} {outcome} @ ${price:.3f} | {title}")

        if side not in ("BUY", "SELL"): return
        if not COPY_SELLS and side == "SELL": return

        target_cost = size * price
        usdc_amount = (target_cost * self.ratio) if USE_RATIO else MY_FIXED_BET_SIZE

        if side == 'BUY':
            limit_price = min(price * (1 + (MAX_SLIPPAGE / 100)), MAX_PRICE_CAP)
        else:
            limit_price = max(price * (1 - (MAX_SLIPPAGE / 100)), MIN_PRICE_CAP)

        desired_shares = float(Decimal(usdc_amount / limit_price).quantize(Decimal('0.1'), rounding=ROUND_DOWN))
        
        if asset_id not in self.subscribed_markets:
            self.subscribed_markets[asset_id] = time.time()
            await self.pending_subscriptions.put(asset_id)

        # SIMULATE FILL
        filled_qty, avg_fill, src = await self.check_liquidity_and_fill(
            asset_id, 
            limit_price, 
            desired_shares, 
            side, 
            force_market_price=is_test 
        )
        
        if filled_qty > 0:
            cost = filled_qty * avg_fill
            logger.info(f"   📝 PAPER TRADE ({src}): {filled_qty:.1f} Shares @ ${avg_fill:.3f} (Cost: ${cost:.2f})")
            
            self.fills_log.append({
                'time': datetime.now().strftime('%H:%M:%S'),
                'asset': asset_id,
                'side': side,
                'price': avg_fill,
                'shares': filled_qty
            })
            await self.calculate_session_pnl()
        else:
            logger.info(f"   ⚠️ COULD NOT SIMULATE FILL (Price out of range or no liquidity)")

        logger.info("-" * 60)

    # --- POLLING ---
    async def poll_target_trades(self):
        url = "https://data-api.polymarket.com/trades"
        logger.info(f"🔄 TRACKING TARGET: {TARGET_WALLET}")

        while True:
            try:
                resp = await self.fetch_url(url, params={"user": TARGET_WALLET, "limit": 20})
                if resp.status_code == 200:
                    trades = resp.json()
                    new_trade_found = False
                    
                    if self.last_trade_timestamp == 0:
                        logger.info(f"📥 Loaded {len(trades)} recent trades for history.")
                        for t in trades:
                            k = f"{t.get('transactionHash')}_{t.get('asset')}"
                            self.seen_trade_hashes.add(k)
                        
                        # --- STARTUP TEST ---
                        if trades and TEST_ON_STARTUP:
                             valid_buys = [t for t in trades if t.get('side') == 'BUY']
                             trade_to_test = valid_buys[0] if valid_buys else trades[0]
                             logger.info(f"🧪 Running TEST on recent trade: {trade_to_test.get('title')[:30]}...")
                             await self.execute_trade(trade_to_test, is_test=True)

                        self.last_trade_timestamp = time.time()
                        logger.info("✅ Startup complete. Waiting for NEW trades...")
                        continue

                    trades.sort(key=lambda x: x.get('timestamp', 0))

                    for trade in trades:
                        k = f"{trade.get('transactionHash')}_{trade.get('asset')}"
                        if k in self.seen_trade_hashes: continue
                        
                        self.seen_trade_hashes.add(k)
                        await self.execute_trade(trade)
                        new_trade_found = True

                    if new_trade_found: continue 

                elif resp.status_code == 429:
                    await asyncio.sleep(5)

            except Exception as e:
                logger.error(f"Polling Error: {e}")
            
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def cleanup_expired_subscriptions(self):
        while True:
            await asyncio.sleep(60)
            now = time.time()
            expired = [k for k,v in self.subscribed_markets.items() if now - v > ORDERBOOK_EXPIRY_SECONDS]
            for k in expired: del self.subscribed_markets[k]; del self.orderbooks[k]

    async def orderbook_websocket(self):
        uri = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
        while True:
            try:
                async with websockets.connect(uri, ping_interval=20) as websocket:
                    self.orderbook_ws = websocket
                    await websocket.send(json.dumps({"type": "market", "assets_ids": []}))
                    logger.info("📚 ORDERBOOK WS: Connected")

                    async def handle_messages():
                        while True:
                            msg = await websocket.recv()
                            data = json.loads(msg)
                            events = data if isinstance(data, list) else [data]
                            for event in events:
                                if event.get('event_type') == 'book' and event.get('asset_id'):
                                    self.orderbooks[event['asset_id']] = {'asks': event.get('asks', []), 'bids': event.get('bids', []), 'timestamp': time.time()}

                    async def handle_subscriptions():
                        while True:
                            asset_id = await self.pending_subscriptions.get()
                            try:
                                await websocket.send(json.dumps({"assets_ids": [asset_id], "operation": "subscribe"}))
                            except:
                                await self.pending_subscriptions.put(asset_id)

                    await asyncio.gather(handle_messages(), handle_subscriptions())
            except Exception:
                await asyncio.sleep(2)

    async def run(self):
        logger.info("🚀 STARTING PolymarketTracker (Free Version)")
        await asyncio.gather(self.poll_target_trades(), self.orderbook_websocket(), self.cleanup_expired_subscriptions())

if __name__ == "__main__":
    bot = PolymarketTracker()
    try:
        asyncio.get_event_loop().run_until_complete(bot.run())
    except KeyboardInterrupt:
        print("\nStopping...")
