import json
import logging
import sys
import schwab


class AutoInvestor:
    def __init__(self, config_file: str = "config.json"):
        self.client = None

        with open(config_file, 'r') as cf:
            self.config = json.load(cf)

        log_level = self.config.get('log_level', 'INFO')
        log_file  = self.config.get('log_file', 'auto_invest.log')

        logging.basicConfig(
            level=getattr(logging, log_level.upper()),
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[logging.FileHandler(log_file), logging.StreamHandler()]
        )

    def authenticate(self):
        schwab_config = self.config['schwab_client']
        self.client = schwab.auth.easy_client(**schwab_config)
        logging.info("Successfully authenticated with Schwab API")

    def get_account_balance(self) -> float:
        assert self.client is not None, "Client not authenticated"
        account_info = self.client.get_account(self.config['account_hash'])
        balance = account_info.json()['securitiesAccount']['currentBalances']['cashBalance']
        logging.info(f"Available funds: ${balance:,.2f}")
        return float(balance)

    def get_current_prices(self, symbols: list[str]) -> dict[str, float]:
        assert self.client is not None, "Client not authenticated"

        quotes = self.client.get_quotes(symbols).json()
        prices = {}

        for symbol in symbols:
            quote = quotes[symbol]['quote']
            price = quote.get('lastPrice') or (quote.get('bidPrice', 0) + quote.get('askPrice', 0)) / 2
            prices[symbol] = float(price) if price else 0.0

        logging.info(f"Current prices: {prices}")
        return prices

    def calculate_allocation(self, available_funds: float, prices: dict[str, float]) -> list[tuple[str, int, float]]:
        orders = []
        for symbol, target_pct in self.config['allocation'].items():
            price = prices.get(symbol, 0)
            if price <= 0: continue

            shares = int(available_funds * target_pct / 100 / price)
            if shares > 0:
                amount = shares * price
                orders.append((symbol, shares, amount))
                logging.info(f"{symbol}: {shares} shares @ ${price:.2f} = ${amount:.2f}")

        return orders

    def place_limit_orders(self, orders: list[tuple[str, int, float]]) -> bool:
        assert self.client is not None, "Client not authenticated"

        if not orders:
            logging.info("No orders to place")
            return True

        dry_run = self.config.get('dry_run', True)
        account_hash = self.config['account_hash']

        if dry_run:
            logging.info("DRY RUN MODE - No actual orders will be placed")
            return self._execute_dry_run_orders(orders)
        else:
            return self._execute_live_orders(orders, account_hash)

    def _execute_dry_run_orders(self, orders: list[tuple[str, int, float]]) -> bool:
        for symbol, shares, _ in orders:
            price = self.get_current_prices([symbol])[symbol]
            logging.info(f"DRY RUN: Would place order for {shares} shares of {symbol} at ${price:.2f}")
        return True

    def _execute_live_orders(self, orders: list[tuple[str, int, float]], account_hash: str) -> bool:
        assert self.client is not None, "Client not authenticated"

        for symbol, shares, _ in orders:
            price = self.get_current_prices([symbol])[symbol]

            order = {
                "orderType": "LIMIT",
                "session": "NORMAL",
                "duration": "DAY",
                "orderStrategyType": "SINGLE",
                "price": f"{price:.2f}",
                "orderLegCollection": [{
                    "instruction": "BUY",
                    "quantity": shares,
                    "instrument": {"symbol": symbol, "assetType": "ETF"}
                }]
            }

            response = self.client.place_order(account_hash, order)
            if response.status_code != 201:
                logging.error(f"Failed to place order for {symbol}: {response.text}")
                return False
            logging.info(f"Successfully placed order for {shares} shares of {symbol}")

        return True

    def run(self):
        logging.info("Starting automated investment process")

        self.authenticate()
        available_funds = self.get_account_balance()

        if available_funds <= 0:
            logging.info("No funds available for investment")
            return

        symbols = list(self.config['allocation'].keys())
        prices = self.get_current_prices(symbols)
        orders = self.calculate_allocation(available_funds, prices)

        if self.place_limit_orders(orders):
            logging.info("Investment process completed successfully")
        else:
            logging.error("Some orders failed - check logs for details")


def main():
    config_file = sys.argv[1] if len(sys.argv) > 1 else "config.json"
    AutoInvestor(config_file).run()


if __name__ == "__main__":
    main()
