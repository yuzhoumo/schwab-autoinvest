# Schwab Autoinvest

Auto-invest available funds based on pre-configured target allocation.

## Setup

1. Copy `config.example.json` to `config.json`
2. Configure your Schwab API credentials and target allocation
3. Install dependencies: `uv sync`

## Usage

```bash
python auto_invest.py [--force-dry-run]
```

`--force-dry-run`: Force dry run regardless of json config option

## Configuration

Define your keys and target allocation in `config.json`:

```json
{
    "schwab_client": {
        "api_key": "YOUR_API_KEY",
        "app_secret": "YOUR_API_SECRET",
        "callback_url": "https://127.0.0.1:8182/",
        "token_path": "./schwab_tokens.json"
    },
    "account_hash": "YOUR_ACCOUNT_HASH",
    "allocation": {
        "VTI": 65,
        "VXUS": 35
    },
    "dry_run": true,
    "log_level": "INFO",
    "log_file": "auto_invest.log",
    "log_file": "{timestamp}_autoinvest.log",
    "email": {
        "enabled": true,
        "smtp_server": "smtp.protonmail.ch",
        "smtp_port": 587,
        "username": "YOUR_FROM_EMAIL@YOUR_DOMAIN.com",
        "password": "YOUR_PASSWORD",
        "from_email": "YOUR_FROM_EMAIL@YOUR_DOMAIN.com",
        "to_email": "YOUR_TO_EMAIL@YOUR_DOMAIN.com",
        "subject": "Schwab Autoinvest Log - {timestamp}"
    }
}
```

The tool calculates optimal whole share purchases to minimize deviation from
target percentages.
