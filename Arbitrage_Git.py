import tkinter as tk
from tkinter import scrolledtext, ttk
import requests
import ccxt
import pandas as pd
import time
import threading
import webbrowser
from datetime import datetime, timedelta
import os

CMC_API_KEY = os.getenv('CMC_API_KEY', 'YOUR_CMC_API_KEY')
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID', 'YOUR_TELEGRAM_CHAT_ID')

exchanges = {
    'binance': ccxt.binance(),
    'crypto.com': ccxt.cryptocom(),
    'gateio': ccxt.gateio(),
    'htx': ccxt.huobi(),
    'xt': ccxt.xt()
}

symbol_to_slug = {}
shown_symbols = {}

def get_coins_200_to_300():
    url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest'
    headers = {'X-CMC_PRO_API_KEY': CMC_API_KEY}
    params = {'start': '100', 'limit': '1500', 'convert': 'USD'}
    response = requests.get(url, headers=headers, params=params)
    data = response.json()['data']
    for coin in data:
        symbol_to_slug[coin['symbol']] = coin['slug']
    return [f"{coin['symbol']}/USDT" for coin in data]

def fetch_ticker_with_retry(exchange, symbol, retries=3, delay=5):
    for attempt in range(retries):
        try:
            return exchange.fetch_ticker(symbol)
        except Exception:
            if attempt < retries - 1:
                time.sleep(delay * (2 ** attempt))
            else:
                return None

def fetch_prices(symbols, batch_size=10):
    arbitrage_opps = []
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        for symbol in batch:
            prices = {}
            for name, ex in exchanges.items():
                try:
                    if symbol in ex.load_markets():
                        ticker = fetch_ticker_with_retry(ex, symbol)
                        prices[name] = ticker['last'] if ticker else None
                except:
                    prices[name] = None
            available_prices = {k: v for k, v in prices.items() if v is not None}
            if len(available_prices) >= 2:
                max_ex = max(available_prices, key=available_prices.get)
                min_ex = min(available_prices, key=available_prices.get)
                max_price = available_prices[max_ex]
                min_price = available_prices[min_ex]
                diff_percent = ((max_price - min_price) / min_price) * 100
                if diff_percent >= 5.0:
                    arbitrage_opps.append({
                        'symbol': symbol,
                        'min_exchange': min_ex,
                        'min_price': round(min_price, 4),
                        'max_exchange': max_ex,
                        'max_price': round(max_price, 4),
                        'difference_%': round(diff_percent, 2)
                    })
        time.sleep(0.2)
    return pd.DataFrame(arbitrage_opps)

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    requests.post(url, data=payload)

def should_show_symbol(symbol):
    now = datetime.now()
    last_shown = shown_symbols.get(symbol)
    if last_shown and now - last_shown < timedelta(hours=1):
        return False
    shown_symbols[symbol] = now
    return True

class ArbitrageApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Crypto Arbitrage Dashboard")
        self.root.geometry("700x520")
        
        self.text_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, font=("Courier", 10))
        self.text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))

        self.controls = tk.Frame(root)
        self.controls.pack(fill=tk.X, pady=5)

        self.refresh_btn = ttk.Button(self.controls, text="🔁 Manual Refresh", command=self.manual_refresh)
        self.refresh_btn.pack(side=tk.LEFT, padx=10)

        self.status_label = tk.Label(self.controls, text="Waiting for manual refresh.", fg="green")
        self.status_label.pack(side=tk.LEFT)

        self.link_buttons = tk.Frame(root)
        self.link_buttons.pack(fill=tk.X, pady=(5, 10))

    def manual_refresh(self):
        threading.Thread(target=self.check_opportunities).start()

    def check_opportunities(self):
        self.status_label.config(text="Scanning for arbitrage opportunities...")
        try:
            symbols = get_coins_200_to_300()
            df = fetch_prices(symbols)
            self.text_area.delete("1.0", tk.END)
            for widget in self.link_buttons.winfo_children():
                widget.destroy()

            if not df.empty:
                for _, row in df.iterrows():
                    symbol = row['symbol'].split('/')[0]
                    if not should_show_symbol(symbol):
                        continue

                    slug = symbol_to_slug.get(symbol, symbol.lower())
                    url = f"https://coinmarketcap.com/currencies/{slug}"
                    msg = (
                        f"\n🚨 {symbol}:\n"
                        f"Buy on {row['min_exchange']} @ ${row['min_price']}\n"
                        f"Sell on {row['max_exchange']} @ ${row['max_price']}\n"
                        f"Profit: {row['difference_%']}%\n"
                        f"View on CoinMarketCap: {url}\n"
                        "-----------------------------------\n"
                    )
                    self.text_area.insert(tk.END, msg)
                    btn = ttk.Button(self.link_buttons, text=f"View {symbol}", command=lambda u=url: webbrowser.open(u))
                    btn.pack(side=tk.LEFT, padx=5, pady=5)

                    alert = (
                        f"🚨 *Arbitrage Opportunity!*\n"
                        f"Symbol: `{row['symbol']}`\n"
                        f"Buy: {row['min_exchange']} @ ${row['min_price']}\n"
                        f"Sell: {row['max_exchange']} @ ${row['max_price']}\n"
                        f"Diff: *{row['difference_%']}%*"
                    )
                    send_telegram_alert(alert)
            else:
                self.text_area.insert(tk.END, "No arbitrage opportunities over 5% found.\n")
            self.status_label.config(text="Last checked ✅")
        except Exception as e:
            self.status_label.config(text=f"Error: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = ArbitrageApp(root)
    root.mainloop()