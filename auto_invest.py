import json
import logging
import sys
import schwab


class AutoInvestor:
    def __init__(self, config_file: str = "config.json"):
        self.config = self._load_config(config_file)
        self.client = None
        self._setup_logging()

    def _load_config(self, config_file: str) -> dict:
        """Load configuration from JSON file"""
        try:
            with open(config_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logging.error(f"Config file {config_file} not found")
            sys.exit(1)
        except json.JSONDecodeError:
            logging.error(f"Invalid JSON in {config_file}")
            sys.exit(1)

    def _setup_logging(self):
        """Configure logging"""
        log_level = self.config.get('log_level', 'INFO')
        log_file = self.config.get('log_file', 'auto_invest.log')

        logging.basicConfig(
            level=getattr(logging, log_level.upper()),
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )

    def authenticate(self):
        """Authenticate with Schwab API"""
        try:
            api_key = self.config['schwab']['api_key']
            app_secret = self.config['schwab']['app_secret']
            token_path = self.config['schwab']['token_path']
            callback_url = self.config['schwab']['callback_url']

            self.client = schwab.auth.easy_client(
                api_key=api_key,
                app_secret=app_secret,
                callback_url=callback_url,
                token_path=token_path,
            )
            logging.info("Successfully authenticated with Schwab API")

        except Exception as e:
            logging.error(f"Authentication failed: {e}")
            sys.exit(1)

    def get_account_balance(self) -> float:
        """Get available cash balance from primary account"""
        if not self.client:
            msg = 'Cannot get account balance before authentication'
            logging.error(msg)
            raise RuntimeError(msg)

        try:
            account_hash = self.config['schwab']['account_hash']
            account_info = self.client.get_account(account_hash)

            balances = account_info.json()['securitiesAccount']['currentBalances']
            available_funds = balances.get('cashBalance', 0)

            logging.info(f"Available funds: ${available_funds:,.2f}")
            return float(available_funds)

        except Exception as e:
            logging.error(f"Error getting account balance: {e}")
            return 0.0

    def get_current_prices(self, symbols: list[str]) -> dict[str, float]:
        """Get current market prices for given symbols"""
        if not self.client:
            msg = 'Cannot get current prices before authentication'
            logging.error(msg)
            raise RuntimeError(msg)

        try:
            quotes = self.client.get_quotes(symbols)
            prices = {}

            for symbol in symbols:
                quote_data = quotes.json()[symbol]['quote']
                # Use last price, fallback to bid/ask midpoint
                last_price = quote_data.get('lastPrice')
                if last_price:
                    prices[symbol] = float(last_price)
                else:
                    bid = quote_data.get('bidPrice', 0)
                    ask = quote_data.get('askPrice', 0)
                    if bid and ask:
                        prices[symbol] = (float(bid) + float(ask)) / 2
                    else:
                        logging.warning(f"No price data available for {symbol}")
                        prices[symbol] = 0.0

            logging.info(f"Current prices: {prices}")
            return prices

        except Exception as e:
            logging.error(f"Error getting current prices: {e}")
            return {}

    def calculate_allocation(self, available_funds: float, prices: dict[str, float]) -> list[tuple[str, int, float]]:
        """
        Calculate optimal share allocation based on target percentages
        Returns list of (symbol, shares, dollar_amount) tuples
        """
        allocations = self.config['allocation']
        min_investment = self.config.get('min_investment_amount', 100)

        if available_funds < min_investment:
            logging.info(f"Available funds ${available_funds:,.2f} below minimum ${min_investment:,.2f}")
            return []

        orders = []
        total_allocated = 0.0

        # Calculate target dollar amounts
        for symbol, target_pct in allocations.items():
            if symbol not in prices or prices[symbol] <= 0:
                logging.warning(f"Skipping {symbol} - no valid price")
                continue

            target_amount = available_funds * (target_pct / 100)
            shares = int(target_amount / prices[symbol])  # Whole shares only
            actual_amount = shares * prices[symbol]

            if shares > 0:
                orders.append((symbol, shares, actual_amount))
                total_allocated += actual_amount
                logging.info(f"{symbol}: {shares} shares @ ${prices[symbol]:.2f} = ${actual_amount:.2f}")

        logging.info(f"Total allocation: ${total_allocated:.2f} of ${available_funds:.2f}")
        return orders

    def place_limit_orders(self, orders: list[tuple[str, int, float]]) -> bool:
        """Place limit orders for calculated allocations"""
        if not self.client:
            msg = 'Cannot get place limit orders before authentication'
            logging.error(msg)
            raise RuntimeError(msg)

        if not orders:
            logging.info("No orders to place")
            return True

        dry_run = self.config.get('dry_run', True)
        account_hash = self.config['schwab']['account_hash']

        if dry_run:
            logging.info("DRY RUN MODE - No actual orders will be placed")

        all_successful = True

        for symbol, shares, _ in orders:
            try:
                # Get current price for limit order
                current_prices = self.get_current_prices([symbol])
                if symbol not in current_prices:
                    logging.error(f"Cannot get current price for {symbol}")
                    all_successful = False
                    continue

                limit_price = current_prices[symbol]

                order = {
                    "orderType": "LIMIT",
                    "session": "NORMAL",
                    "duration": "DAY",
                    "orderStrategyType": "SINGLE",
                    "price": f"{limit_price:.2f}",
                    "orderLegCollection": [{
                        "instruction": "BUY",
                        "quantity": shares,
                        "instrument": {
                            "symbol": symbol,
                            "assetType": "ETF"
                        }
                    }]
                }

                if dry_run:
                    logging.info(f"DRY RUN: Would place order for {shares} shares of {symbol} at ${limit_price:.2f}")
                else:
                    response = self.client.place_order(account_hash, order)
                    if response.status_code == 201:
                        logging.info(f"Successfully placed order for {shares} shares of {symbol}")
                    else:
                        logging.error(f"Failed to place order for {symbol}: {response.text}")
                        all_successful = False

            except Exception as e:
                logging.error(f"Error placing order for {symbol}: {e}")
                all_successful = False

        return all_successful

    def run(self):
        """Main execution method"""
        logging.info("Starting automated investment process")

        try:
            # Authenticate
            self.authenticate()

            # Get available balance
            available_funds = self.get_account_balance()
            if available_funds <= 0:
                logging.info("No funds available for investment")
                return

            # Get current prices
            symbols = list(self.config['allocation'].keys())
            prices = self.get_current_prices(symbols)

            # Calculate allocation
            orders = self.calculate_allocation(available_funds, prices)

            # Place orders
            success = self.place_limit_orders(orders)

            if success:
                logging.info("Investment process completed successfully")
            else:
                logging.error("Some orders failed - check logs for details")

        except Exception as e:
            logging.error(f"Unexpected error in investment process: {e}")
            raise


def main():
    """Main entry point"""
    config_file = sys.argv[1] if len(sys.argv) > 1 else "config.json"

    investor = AutoInvestor(config_file)
    investor.run()


if __name__ == "__main__":
    main()
