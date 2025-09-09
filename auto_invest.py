import asyncio
import json
import logging
import sys
from typing import cast
from schwab.auth import easy_client
from schwab.client import AsyncClient
from schwab.orders.equities import equity_buy_limit, Duration, Session

def calculate_optimal_allocation(cash: float, prices: dict[str, float], allocation: dict[str, int]) -> dict[str, int]:
    total_weight = sum(allocation.values())
    target_amounts = {symbol: cash * (weight / total_weight) for symbol, weight in allocation.items()}

    shares = {symbol: 0 for symbol in allocation.keys()}
    remaining_cash = cash

    while remaining_cash > 0:
        best_symbol = None
        best_score = float('-inf')

        for symbol in allocation.keys():
            if prices[symbol] > remaining_cash or prices[symbol] <= 0:
                continue

            current_value = shares[symbol] * prices[symbol]
            new_value = current_value + prices[symbol]

            # Calculate how much this purchase reduces the relative deviation
            if target_amounts[symbol] > 0:
                current_deviation = abs(current_value - target_amounts[symbol]) / target_amounts[symbol]
                new_deviation = abs(new_value - target_amounts[symbol]) / target_amounts[symbol]
            else:
                current_deviation = new_deviation = 0

            # Score is the relative improvement per dollar spent
            improvement = current_deviation - new_deviation
            score = improvement / prices[symbol] if prices[symbol] > 0 else 0

            if score > best_score:
                best_score = score
                best_symbol = symbol

        if best_symbol is None or best_score <= 0:
            break

        shares[best_symbol] += 1
        remaining_cash -= prices[best_symbol]

    logging.info(f"Optimal allocation: {shares}")
    logging.info(f"Remaining cash: ${remaining_cash:.2f}")

    return shares


async def get_account_cash(client: AsyncClient, account_hash: str) -> float:
    account_info = await client.get_account(account_hash)
    balance = account_info.json()['securitiesAccount']['currentBalances']['cashBalance']
    logging.info(f"Available cash: ${balance:,.2f}")
    return float(balance)


async def get_current_prices(client: AsyncClient, symbols: list[str]) -> dict[str, float]:
    quotes_response = await client.get_quotes(symbols)
    quotes = quotes_response.json()
    prices = {}
    for symbol in symbols:
        price = quotes[symbol]['quote'].get('lastPrice')
        prices[symbol] = float(price) if price else 0.0
    logging.info(f"Current prices: {prices}")
    return prices


async def check_existing_orders(client: AsyncClient, account_hash: str) -> bool:
    open_statuses = [
        AsyncClient.Order.Status.AWAITING_PARENT_ORDER,
        AsyncClient.Order.Status.AWAITING_CONDITION,
        AsyncClient.Order.Status.AWAITING_MANUAL_REVIEW,
        AsyncClient.Order.Status.ACCEPTED,
        AsyncClient.Order.Status.AWAITING_UR_OUT,
        AsyncClient.Order.Status.PENDING_ACTIVATION,
        AsyncClient.Order.Status.QUEUED,
        AsyncClient.Order.Status.WORKING,
        AsyncClient.Order.Status.PENDING_CANCEL,
        AsyncClient.Order.Status.PENDING_REPLACE,
    ]

    tasks = [client.get_orders_for_account(account_hash, status=s) for s in open_statuses]
    responses = await asyncio.gather(*tasks)

    for response in responses:
        if response.json():
            logging.warning("Found existing open orders - cancelling script")
            return True

    logging.info("No existing open orders found")
    return False


async def place_limit_orders(client: AsyncClient, account_hash: str, allocation: dict[str, int], dry_run: bool = True):
    symbols = list(allocation.keys())
    cash, prices = await asyncio.gather(
        get_account_cash(client, account_hash),
        get_current_prices(client, symbols),
    )
    shares_to_buy = calculate_optimal_allocation(cash, prices, allocation)

    order_tasks = []
    for symbol, quantity in shares_to_buy.items():
        if quantity == 0: continue

        price = prices[symbol]
        order_value = quantity * price

        logging.info(f"Place limit order: {quantity} shares of {symbol} at ${price:.2f} (total: ${order_value:.2f})")

        if dry_run:
            logging.info("DRY RUN: Order not actually placed")
            continue

        order = equity_buy_limit(symbol, quantity, price)
        order.set_duration(Duration.DAY)
        order.set_session(Session.NORMAL)
        order_tasks.append(client.place_order(account_hash, order))

    responses = await asyncio.gather(*order_tasks)
    order_symbols = [symbol for symbol, quantity in shares_to_buy.items() if quantity > 0]
    for symbol, resp in zip(order_symbols, responses):
        if resp.status_code >= 400:
            logging.error(f"Failed to place order for {symbol}: {resp.status_code}")
        else:
            logging.info(f"Order placed successfully for {symbol}")


async def main():
    config_file = sys.argv[1] if len(sys.argv) > 1 else "config.json"
    with open(config_file, 'r') as cf:
        config = json.load(cf)

    log_level = config.get('log_level', 'INFO')
    log_file  = config.get('log_file', 'auto_invest.log')
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()]
    )

    client_config = config['schwab_client']
    api_key       = client_config['api_key']
    app_secret    = client_config['app_secret']
    callback_url  = client_config['callback_url']
    token_path    = client_config['token_path']

    logging.info("Starting automated investment process")
    client = cast(AsyncClient, easy_client(api_key, app_secret, callback_url, token_path, asyncio=True))

    if await check_existing_orders(client, config['account_hash']):
        logging.error("Script cancelled due to existing open orders")
        return

    await place_limit_orders(
        client, config['account_hash'], config['allocation'], config['dry_run']
    )


if __name__ == "__main__":
    asyncio.run(main())
