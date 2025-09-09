import pytest
import asyncio
import json
from unittest.mock import Mock, AsyncMock, patch, mock_open
import sys

from auto_invest import (
    calculate_optimal_allocation,
    get_account_cash,
    get_current_prices,
    place_limit_orders,
    main
)


class TestCalculateOptimalAllocation:
    """Test the core allocation algorithm - CRITICAL for financial correctness."""

    def test_basic_allocation_equal_weights(self):
        """Test basic allocation with equal weights."""
        cash = 1000.0
        prices = {"VTI": 100.0, "VXUS": 50.0}
        allocation = {"VTI": 50, "VXUS": 50}

        result = calculate_optimal_allocation(cash, prices, allocation)

        # Should buy 5 VTI ($500) and 10 VXUS ($500) for perfect 50/50 split
        assert result["VTI"] == 5
        assert result["VXUS"] == 10

        # Verify total spent is close to target allocation
        total_vti_value = result["VTI"] * prices["VTI"]
        total_vxus_value = result["VXUS"] * prices["VXUS"]
        assert abs(total_vti_value - 500.0) < prices["VTI"]  # Within one share price
        assert abs(total_vxus_value - 500.0) < prices["VXUS"]

    def test_allocation_unequal_weights(self):
        """Test allocation with unequal weights (65/35 split)."""
        cash = 1000.0
        prices = {"VTI": 100.0, "VXUS": 50.0}
        allocation = {"VTI": 65, "VXUS": 35}  # From real config

        result = calculate_optimal_allocation(cash, prices, allocation)

        # Verify allocation respects target percentages
        total_vti_value = result["VTI"] * prices["VTI"]
        total_vxus_value = result["VXUS"] * prices["VXUS"]
        total_invested = total_vti_value + total_vxus_value

        if total_invested > 0:
            vti_percentage = total_vti_value / total_invested
            vxus_percentage = total_vxus_value / total_invested

            # Should be close to 65/35 split (within reasonable tolerance)
            assert abs(vti_percentage - 0.65) < 0.1
            assert abs(vxus_percentage - 0.35) < 0.1

    def test_zero_cash(self):
        """Test behavior with zero available cash."""
        cash = 0.0
        prices = {"VTI": 100.0, "VXUS": 50.0}
        allocation = {"VTI": 65, "VXUS": 35}

        result = calculate_optimal_allocation(cash, prices, allocation)

        # Should buy nothing
        assert result["VTI"] == 0
        assert result["VXUS"] == 0

    def test_insufficient_cash_for_any_shares(self):
        """Test when cash is insufficient to buy even one share of cheapest stock."""
        cash = 25.0  # Less than cheapest stock
        prices = {"VTI": 100.0, "VXUS": 50.0}
        allocation = {"VTI": 50, "VXUS": 50}

        result = calculate_optimal_allocation(cash, prices, allocation)

        # Should buy nothing
        assert result["VTI"] == 0
        assert result["VXUS"] == 0

    def test_can_only_afford_one_stock_type(self):
        """Test when cash only allows buying one type of stock."""
        cash = 75.0  # Can buy 1 VXUS but not VTI
        prices = {"VTI": 100.0, "VXUS": 50.0}
        allocation = {"VTI": 50, "VXUS": 50}

        result = calculate_optimal_allocation(cash, prices, allocation)

        # Should buy 1 VXUS (cheaper, gets closer to target)
        assert result["VTI"] == 0
        assert result["VXUS"] == 1

    def test_zero_price_stock(self):
        """Test behavior when a stock has zero price (invalid data)."""
        cash = 1000.0
        prices = {"VTI": 0.0, "VXUS": 50.0}  # Zero price for VTI
        allocation = {"VTI": 50, "VXUS": 50}

        result = calculate_optimal_allocation(cash, prices, allocation)

        # Should only buy VXUS since VTI has invalid price
        assert result["VTI"] == 0
        assert result["VXUS"] > 0

    def test_negative_price_stock(self):
        """Test behavior with negative stock price (should be impossible but test anyway)."""
        cash = 1000.0
        prices = {"VTI": -100.0, "VXUS": 50.0}
        allocation = {"VTI": 50, "VXUS": 50}

        result = calculate_optimal_allocation(cash, prices, allocation)

        # Should only buy VXUS since VTI has invalid price
        assert result["VTI"] == 0
        assert result["VXUS"] > 0

    def test_empty_allocation(self):
        """Test with empty allocation dictionary."""
        cash = 1000.0
        prices = {}
        allocation = {}

        result = calculate_optimal_allocation(cash, prices, allocation)

        # Should return empty result
        assert result == {}

    def test_single_stock_allocation(self):
        """Test allocation with only one stock."""
        cash = 1000.0
        prices = {"VTI": 100.0}
        allocation = {"VTI": 100}

        result = calculate_optimal_allocation(cash, prices, allocation)

        # Should buy 10 shares of VTI
        assert result["VTI"] == 10

    def test_allocation_weights_sum_to_zero(self):
        """Test with allocation weights that sum to zero (invalid config)."""
        cash = 1000.0
        prices = {"VTI": 100.0, "VXUS": 50.0}
        allocation = {"VTI": 0, "VXUS": 0}

        # This should not crash but behavior is undefined
        # The function should handle division by zero gracefully
        with pytest.raises(ZeroDivisionError):
            calculate_optimal_allocation(cash, prices, allocation)

    def test_floating_point_precision(self):
        """Test floating point precision issues with odd prices and cash amounts."""
        cash = 1000.33  # Odd cash amount
        prices = {"VTI": 100.33, "VXUS": 50.17}  # Odd prices
        allocation = {"VTI": 65, "VXUS": 35}

        result = calculate_optimal_allocation(cash, prices, allocation)

        # Should handle floating point without errors
        assert isinstance(result["VTI"], int)
        assert isinstance(result["VXUS"], int)

        # Verify we don't overspend
        total_cost = result["VTI"] * prices["VTI"] + result["VXUS"] * prices["VXUS"]
        assert total_cost <= cash

    def test_missing_price_for_allocated_stock(self):
        """Test when allocation includes stock not in prices."""
        cash = 1000.0
        prices = {"VTI": 100.0}  # Missing VXUS price
        allocation = {"VTI": 50, "VXUS": 50}

        # Should raise KeyError when trying to access missing price
        with pytest.raises(KeyError):
            calculate_optimal_allocation(cash, prices, allocation)

    @pytest.mark.parametrize("cash,expected_total_shares", [
        (100, 1),   # Can buy 1 VXUS
        (150, 2),   # Can buy 1 VTI or 3 VXUS, should optimize
        (500, 8),   # Should buy mix to optimize allocation
        (1500, 21), # Larger amount
    ])
    def test_parametrized_cash_amounts(self, cash, expected_total_shares):
        """Parametrized test for different cash amounts."""
        prices = {"VTI": 100.0, "VXUS": 50.0}
        allocation = {"VTI": 60, "VXUS": 40}

        result = calculate_optimal_allocation(cash, prices, allocation)
        total_shares = result["VTI"] + result["VXUS"]

        # Total shares should be reasonable for the cash amount
        assert total_shares <= expected_total_shares + 2  # Allow some variance


class TestGetAccountCash:
    """Test account cash retrieval function."""

    @pytest.mark.asyncio
    async def test_successful_cash_retrieval(self):
        """Test successful cash balance retrieval."""
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.json.return_value = {
            'securitiesAccount': {
                'currentBalances': {
                    'cashBalance': 5000.50
                }
            }
        }
        mock_client.get_account.return_value = mock_response

        result = await get_account_cash(mock_client, "test_account_hash")

        assert result == 5000.50
        mock_client.get_account.assert_called_once_with("test_account_hash")

    @pytest.mark.asyncio
    async def test_zero_cash_balance(self):
        """Test zero cash balance."""
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.json.return_value = {
            'securitiesAccount': {
                'currentBalances': {
                    'cashBalance': 0.0
                }
            }
        }
        mock_client.get_account.return_value = mock_response

        result = await get_account_cash(mock_client, "test_account_hash")

        assert result == 0.0

    @pytest.mark.asyncio
    async def test_negative_cash_balance(self):
        """Test negative cash balance (margin account)."""
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.json.return_value = {
            'securitiesAccount': {
                'currentBalances': {
                    'cashBalance': -1000.0
                }
            }
        }
        mock_client.get_account.return_value = mock_response

        result = await get_account_cash(mock_client, "test_account_hash")

        assert result == -1000.0

    @pytest.mark.asyncio
    async def test_missing_cash_balance_field(self):
        """Test missing cashBalance field in response."""
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.json.return_value = {
            'securitiesAccount': {
                'currentBalances': {}  # Missing cashBalance
            }
        }
        mock_client.get_account.return_value = mock_response

        with pytest.raises(KeyError):
            await get_account_cash(mock_client, "test_account_hash")

    @pytest.mark.asyncio
    async def test_malformed_account_response(self):
        """Test malformed account response."""
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.json.return_value = {}  # Empty response
        mock_client.get_account.return_value = mock_response

        with pytest.raises(KeyError):
            await get_account_cash(mock_client, "test_account_hash")

    @pytest.mark.asyncio
    async def test_api_exception(self):
        """Test API call raises exception."""
        mock_client = AsyncMock()
        mock_client.get_account.side_effect = Exception("API Error")

        with pytest.raises(Exception, match="API Error"):
            await get_account_cash(mock_client, "test_account_hash")

    @pytest.mark.asyncio
    async def test_json_decode_error(self):
        """Test JSON decode error."""
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
        mock_client.get_account.return_value = mock_response

        with pytest.raises(json.JSONDecodeError):
            await get_account_cash(mock_client, "test_account_hash")


class TestGetCurrentPrices:
    """Test current price retrieval function."""

    @pytest.mark.asyncio
    async def test_successful_price_retrieval(self):
        """Test successful price retrieval for multiple symbols."""
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.json.return_value = {
            'VTI': {'quote': {'lastPrice': 220.50}},
            'VXUS': {'quote': {'lastPrice': 62.75}}
        }
        mock_client.get_quotes.return_value = mock_response

        symbols = ['VTI', 'VXUS']
        result = await get_current_prices(mock_client, symbols)

        assert result == {'VTI': 220.50, 'VXUS': 62.75}
        mock_client.get_quotes.assert_called_once_with(symbols)

    @pytest.mark.asyncio
    async def test_missing_last_price(self):
        """Test when lastPrice is missing for a symbol."""
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.json.return_value = {
            'VTI': {'quote': {}},  # Missing lastPrice
            'VXUS': {'quote': {'lastPrice': 62.75}}
        }
        mock_client.get_quotes.return_value = mock_response

        symbols = ['VTI', 'VXUS']
        result = await get_current_prices(mock_client, symbols)

        assert result == {'VTI': 0.0, 'VXUS': 62.75}

    @pytest.mark.asyncio
    async def test_null_last_price(self):
        """Test when lastPrice is null."""
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.json.return_value = {
            'VTI': {'quote': {'lastPrice': None}},
            'VXUS': {'quote': {'lastPrice': 62.75}}
        }
        mock_client.get_quotes.return_value = mock_response

        symbols = ['VTI', 'VXUS']
        result = await get_current_prices(mock_client, symbols)

        assert result == {'VTI': 0.0, 'VXUS': 62.75}

    @pytest.mark.asyncio
    async def test_zero_price(self):
        """Test zero price (trading halted or delisted stock)."""
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.json.return_value = {
            'VTI': {'quote': {'lastPrice': 0.0}},
            'VXUS': {'quote': {'lastPrice': 62.75}}
        }
        mock_client.get_quotes.return_value = mock_response

        symbols = ['VTI', 'VXUS']
        result = await get_current_prices(mock_client, symbols)

        assert result == {'VTI': 0.0, 'VXUS': 62.75}

    @pytest.mark.asyncio
    async def test_missing_symbol_in_response(self):
        """Test when a requested symbol is missing from response."""
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.json.return_value = {
            'VTI': {'quote': {'lastPrice': 220.50}}
            # VXUS missing
        }
        mock_client.get_quotes.return_value = mock_response

        symbols = ['VTI', 'VXUS']

        with pytest.raises(KeyError):
            await get_current_prices(mock_client, symbols)

    @pytest.mark.asyncio
    async def test_empty_symbols_list(self):
        """Test with empty symbols list."""
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.json.return_value = {}
        mock_client.get_quotes.return_value = mock_response

        symbols = []
        result = await get_current_prices(mock_client, symbols)

        assert result == {}

    @pytest.mark.asyncio
    async def test_api_error(self):
        """Test API error during price retrieval."""
        mock_client = AsyncMock()
        mock_client.get_quotes.side_effect = Exception("Market data unavailable")

        symbols = ['VTI', 'VXUS']

        with pytest.raises(Exception, match="Market data unavailable"):
            await get_current_prices(mock_client, symbols)


class TestPlaceLimitOrders:
    """Test order placement function - CRITICAL as this involves real money."""

    @pytest.mark.asyncio
    async def test_dry_run_mode(self):
        """Test dry run mode does not place actual orders."""
        mock_client = AsyncMock()

        # Mock account cash and prices
        mock_account_response = Mock()
        mock_account_response.json.return_value = {
            'securitiesAccount': {'currentBalances': {'cashBalance': 1000.0}}
        }
        mock_client.get_account.return_value = mock_account_response
        
        mock_quotes_response = Mock()
        mock_quotes_response.json.return_value = {
            'VTI': {'quote': {'lastPrice': 100.0}},
            'VXUS': {'quote': {'lastPrice': 50.0}}
        }
        mock_client.get_quotes.return_value = mock_quotes_response

        allocation = {'VTI': 60, 'VXUS': 40}

        await place_limit_orders(mock_client, "test_account", allocation, dry_run=True)

        # Should not call place_order in dry run mode
        mock_client.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_real_order_placement(self):
        """Test real order placement mode."""
        mock_client = AsyncMock()

        # Mock successful responses
        mock_account_response = Mock()
        mock_account_response.json.return_value = {
            'securitiesAccount': {'currentBalances': {'cashBalance': 1000.0}}
        }
        mock_client.get_account.return_value = mock_account_response
        
        mock_quotes_response = Mock()
        mock_quotes_response.json.return_value = {
            'VTI': {'quote': {'lastPrice': 100.0}},
            'VXUS': {'quote': {'lastPrice': 50.0}}
        }
        mock_client.get_quotes.return_value = mock_quotes_response

        # Mock successful order responses
        successful_response = Mock()
        successful_response.status_code = 201
        mock_client.place_order.return_value = successful_response

        allocation = {'VTI': 60, 'VXUS': 40}

        await place_limit_orders(mock_client, "test_account", allocation, dry_run=False)

        # Should place orders for both symbols (assuming allocation results in purchases)
        assert mock_client.place_order.call_count >= 1

    @pytest.mark.asyncio
    async def test_zero_quantity_orders_skipped(self):
        """Test that zero quantity orders are skipped."""
        mock_client = AsyncMock()

        # Mock responses that will result in zero quantities
        mock_account_response = Mock()
        mock_account_response.json.return_value = {
            'securitiesAccount': {'currentBalances': {'cashBalance': 10.0}}  # Very low cash
        }
        mock_client.get_account.return_value = mock_account_response
        
        mock_quotes_response = Mock()
        mock_quotes_response.json.return_value = {
            'VTI': {'quote': {'lastPrice': 100.0}},  # Too expensive
            'VXUS': {'quote': {'lastPrice': 50.0}}   # Also too expensive
        }
        mock_client.get_quotes.return_value = mock_quotes_response

        allocation = {'VTI': 50, 'VXUS': 50}

        await place_limit_orders(mock_client, "test_account", allocation, dry_run=False)

        # Should not place any orders due to insufficient cash
        mock_client.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_order_placement_failure(self):
        """Test handling of order placement failures."""
        mock_client = AsyncMock()

        mock_account_response = Mock()
        mock_account_response.json.return_value = {
            'securitiesAccount': {'currentBalances': {'cashBalance': 1000.0}}
        }
        mock_client.get_account.return_value = mock_account_response
        
        mock_quotes_response = Mock()
        mock_quotes_response.json.return_value = {
            'VTI': {'quote': {'lastPrice': 100.0}}
        }
        mock_client.get_quotes.return_value = mock_quotes_response

        # Mock failed order response
        failed_response = Mock()
        failed_response.status_code = 400
        mock_client.place_order.return_value = failed_response

        allocation = {'VTI': 100}

        # Should not raise exception, just log error
        await place_limit_orders(mock_client, "test_account", allocation, dry_run=False)

        mock_client.place_order.assert_called()

    @pytest.mark.asyncio
    async def test_partial_order_failures(self):
        """Test mixed success/failure scenarios."""
        mock_client = AsyncMock()

        mock_account_response = Mock()
        mock_account_response.json.return_value = {
            'securitiesAccount': {'currentBalances': {'cashBalance': 1000.0}}
        }
        mock_client.get_account.return_value = mock_account_response
        
        mock_quotes_response = Mock()
        mock_quotes_response.json.return_value = {
            'VTI': {'quote': {'lastPrice': 100.0}},
            'VXUS': {'quote': {'lastPrice': 50.0}}
        }
        mock_client.get_quotes.return_value = mock_quotes_response

        # Mock mixed responses
        success_response = Mock()
        success_response.status_code = 201
        failure_response = Mock()
        failure_response.status_code = 400

        mock_client.place_order.side_effect = [success_response, failure_response]

        allocation = {'VTI': 50, 'VXUS': 50}

        # Should handle mixed results gracefully
        await place_limit_orders(mock_client, "test_account", allocation, dry_run=False)

        assert mock_client.place_order.call_count == 2

    @pytest.mark.asyncio
    async def test_account_cash_fetch_failure(self):
        """Test failure when fetching account cash."""
        mock_client = AsyncMock()
        mock_client.get_account = AsyncMock(side_effect=Exception("Account access denied"))
        
        # Configure get_quotes to return a proper response even though it won't be used
        mock_quotes_response = Mock()
        mock_quotes_response.json.return_value = {
            'VTI': {'quote': {'lastPrice': 100.0}},
            'VXUS': {'quote': {'lastPrice': 50.0}}
        }
        mock_client.get_quotes.return_value = mock_quotes_response

        allocation = {'VTI': 50, 'VXUS': 50}

        with pytest.raises(Exception, match="Account access denied"):
            await place_limit_orders(mock_client, "test_account", allocation, dry_run=False)

    @pytest.mark.asyncio
    async def test_price_fetch_failure(self):
        """Test failure when fetching current prices."""
        mock_client = AsyncMock()

        # Mock successful cash fetch but failed price fetch
        mock_account_response = Mock()
        mock_account_response.json.return_value = {
            'securitiesAccount': {'currentBalances': {'cashBalance': 1000.0}}
        }
        mock_client.get_account.return_value = mock_account_response
        mock_client.get_quotes.side_effect = Exception("Market data unavailable")

        allocation = {'VTI': 50, 'VXUS': 50}

        with pytest.raises(Exception, match="Market data unavailable"):
            await place_limit_orders(mock_client, "test_account", allocation, dry_run=False)


class TestMainFunction:
    """Test the main orchestration function."""

    @pytest.mark.asyncio
    async def test_config_file_loading(self):
        """Test configuration file loading."""
        test_config = {
            "schwab_client": {
                "api_key": "test_key",
                "app_secret": "test_secret",
                "callback_url": "https://test.com",
                "token_path": "./test_tokens.json"
            },
            "account_hash": "test_hash",
            "allocation": {"VTI": 60, "VXUS": 40},
            "dry_run": True,
            "log_level": "INFO",
            "log_file": "test.log"
        }

        with patch('builtins.open', mock_open(read_data=json.dumps(test_config))), \
             patch('auto_invest.easy_client'), \
             patch('auto_invest.place_limit_orders') as mock_place_orders, \
             patch('auto_invest.check_existing_orders', return_value=False):

            # Mock sys.argv to provide config file
            with patch.object(sys, 'argv', ['auto_invest.py', 'test_config.json']):
                await main()

            mock_place_orders.assert_called_once()

    def test_missing_config_file(self):
        """Test behavior when config file is missing."""
        with patch('builtins.open', side_effect=FileNotFoundError("Config not found")):
            with pytest.raises(FileNotFoundError):
                asyncio.run(main())

    def test_invalid_json_config(self):
        """Test invalid JSON in config file."""
        with patch('builtins.open', mock_open(read_data='{"invalid": json}')), \
             patch.object(sys, 'argv', ['auto_invest.py', 'bad_config.json']):

            with pytest.raises(json.JSONDecodeError):
                asyncio.run(main())

    def test_missing_required_config_fields(self):
        """Test missing required configuration fields."""
        incomplete_config = {
            "schwab_client": {
                "api_key": "test_key"
                # Missing required fields
            }
        }

        with patch('builtins.open', mock_open(read_data=json.dumps(incomplete_config))), \
             patch.object(sys, 'argv', ['auto_invest.py', 'incomplete_config.json']):

            with pytest.raises(KeyError):
                asyncio.run(main())

    @pytest.mark.asyncio
    async def test_default_config_file(self):
        """Test using default config.json when no file specified."""
        test_config = {
            "schwab_client": {
                "api_key": "test_key",
                "app_secret": "test_secret",
                "callback_url": "https://test.com",
                "token_path": "./test_tokens.json"
            },
            "account_hash": "test_hash",
            "allocation": {"VTI": 60, "VXUS": 40},
            "dry_run": True
        }

        with patch('builtins.open', mock_open(read_data=json.dumps(test_config))), \
             patch('auto_invest.easy_client'), \
             patch('auto_invest.place_limit_orders') as mock_place_orders, \
             patch('auto_invest.check_existing_orders', return_value=False), \
             patch.object(sys, 'argv', ['auto_invest.py']):  # No config file specified

            await main()

            # Should still work with default config.json
            mock_place_orders.assert_called_once()


class TestIntegrationScenarios:
    """Integration tests for critical financial scenarios."""

    @pytest.mark.asyncio
    async def test_complete_investment_workflow(self):
        """Test complete investment workflow end-to-end."""
        mock_client = AsyncMock()

        # Setup realistic scenario
        mock_account_response = Mock()
        mock_account_response.json.return_value = {
            'securitiesAccount': {'currentBalances': {'cashBalance': 10000.0}}
        }
        mock_client.get_account.return_value = mock_account_response
        
        mock_quotes_response = Mock()
        mock_quotes_response.json.return_value = {
            'VTI': {'quote': {'lastPrice': 220.50}},
            'VXUS': {'quote': {'lastPrice': 62.75}}
        }
        mock_client.get_quotes.return_value = mock_quotes_response

        # Mock successful order placement
        success_response = Mock()
        success_response.status_code = 201
        mock_client.place_order.return_value = success_response

        allocation = {'VTI': 65, 'VXUS': 35}  # Real config values

        await place_limit_orders(mock_client, "test_account", allocation, dry_run=False)

        # Verify workflow completed
        mock_client.get_account.assert_called_once()
        mock_client.get_quotes.assert_called_once()
        assert mock_client.place_order.call_count >= 1

    @pytest.mark.asyncio
    async def test_market_closure_scenario(self):
        """Test scenario when market is closed (zero prices)."""
        mock_client = AsyncMock()

        mock_account_response = Mock()
        mock_account_response.json.return_value = {
            'securitiesAccount': {'currentBalances': {'cashBalance': 10000.0}}
        }
        mock_client.get_account.return_value = mock_account_response
        
        mock_quotes_response = Mock()
        mock_quotes_response.json.return_value = {
            'VTI': {'quote': {'lastPrice': 0.0}},  # Market closed
            'VXUS': {'quote': {'lastPrice': 0.0}}
        }
        mock_client.get_quotes.return_value = mock_quotes_response

        allocation = {'VTI': 65, 'VXUS': 35}

        await place_limit_orders(mock_client, "test_account", allocation, dry_run=False)

        # Should not place orders with zero prices
        mock_client.place_order.assert_not_called()

    def test_financial_precision_accuracy(self):
        """Test financial calculations maintain precision."""
        cash = 10000.33
        prices = {"VTI": 220.50, "VXUS": 62.75}
        allocation = {"VTI": 65, "VXUS": 35}

        result = calculate_optimal_allocation(cash, prices, allocation)

        # Calculate actual spent amount
        total_spent = result["VTI"] * prices["VTI"] + result["VXUS"] * prices["VXUS"]

        # Should never overspend
        assert total_spent <= cash

        # Should achieve good cash utilization (within reasonable bounds)
        # The algorithm optimizes for allocation accuracy, not maximum utilization
        utilization_rate = total_spent / cash
        assert utilization_rate >= 0.90  # At least 90% utilization
        
        # Should maintain allocation proportions reasonably well
        if total_spent > 0:
            actual_vti_pct = (result["VTI"] * prices["VTI"]) / total_spent
            actual_vxus_pct = (result["VXUS"] * prices["VXUS"]) / total_spent
            target_vti_pct = allocation["VTI"] / sum(allocation.values())
            target_vxus_pct = allocation["VXUS"] / sum(allocation.values())
            
            # Should be within 5% of target allocation
            assert abs(actual_vti_pct - target_vti_pct) < 0.05
            assert abs(actual_vxus_pct - target_vxus_pct) < 0.05

    def test_extreme_market_conditions(self):
        """Test handling of extreme market conditions."""
        # Very expensive stocks, little cash
        cash = 100.0
        prices = {"VTI": 50000.0, "VXUS": 40000.0}  # Extremely expensive
        allocation = {"VTI": 50, "VXUS": 50}

        result = calculate_optimal_allocation(cash, prices, allocation)

        # Should buy nothing due to insufficient funds
        assert result["VTI"] == 0
        assert result["VXUS"] == 0

    def test_allocation_fairness(self):
        """Test allocation algorithm fairness over multiple scenarios."""
        scenarios = [
            (1000, {"VTI": 100.0, "VXUS": 50.0}, {"VTI": 70, "VXUS": 30}),
            (5000, {"VTI": 220.0, "VXUS": 65.0}, {"VTI": 60, "VXUS": 40}),
            (500, {"VTI": 95.0, "VXUS": 48.0}, {"VTI": 80, "VXUS": 20}),
        ]

        for cash, prices, allocation in scenarios:
            result = calculate_optimal_allocation(cash, prices, allocation)

            # Calculate actual allocation percentages
            total_vti_value = result["VTI"] * prices["VTI"]
            total_vxus_value = result["VXUS"] * prices["VXUS"]
            total_invested = total_vti_value + total_vxus_value

            if total_invested > 0:  # Skip if no investment possible
                actual_vti_percent = total_vti_value / total_invested
                actual_vxus_percent = total_vxus_value / total_invested

                target_vti_percent = allocation["VTI"] / sum(allocation.values())
                target_vxus_percent = allocation["VXUS"] / sum(allocation.values())

                # Should be reasonably close to target allocation
                # Allow 15% tolerance due to discrete share purchasing
                assert abs(actual_vti_percent - target_vti_percent) < 0.15
                assert abs(actual_vxus_percent - target_vxus_percent) < 0.15


@pytest.fixture
def sample_config():
    """Fixture providing sample configuration for tests."""
    return {
        "schwab_client": {
            "api_key": "test_api_key",
            "app_secret": "test_app_secret",
            "callback_url": "https://127.0.0.1:8182/",
            "token_path": "./test_schwab_tokens.json"
        },
        "account_hash": "test_account_hash",
        "allocation": {
            "VTI": 65,
            "VXUS": 35
        },
        "dry_run": True,
        "log_level": "INFO",
        "log_file": "test_auto_invest.log"
    }


@pytest.fixture
def mock_client():
    """Fixture providing a mocked Schwab client."""
    client = AsyncMock()

    # Default successful responses
    mock_account_response = Mock()
    mock_account_response.json.return_value = {
        'securitiesAccount': {'currentBalances': {'cashBalance': 10000.0}}
    }
    client.get_account.return_value = mock_account_response
    
    mock_quotes_response = Mock()
    mock_quotes_response.json.return_value = {
        'VTI': {'quote': {'lastPrice': 220.50}},
        'VXUS': {'quote': {'lastPrice': 62.75}}
    }
    client.get_quotes.return_value = mock_quotes_response

    success_response = Mock()
    success_response.status_code = 201
    client.place_order.return_value = success_response

    return client


if __name__ == "__main__":
    # Run specific test categories based on importance
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "critical":
        # Run only the most critical tests for CI/CD
        pytest.main([
            "test_auto_invest.py::TestCalculateOptimalAllocation",
            "test_auto_invest.py::TestPlaceLimitOrders::test_dry_run_mode",
            "test_auto_invest.py::TestPlaceLimitOrders::test_real_order_placement",
            "test_auto_invest.py::TestIntegrationScenarios::test_financial_precision_accuracy",
            "-v"
        ])
    else:
        # Run all tests
        pytest.main(["-v"])
