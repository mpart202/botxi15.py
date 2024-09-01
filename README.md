# BOTXI Cryptocurrency Trading Bot

## Overview

"IMPORTANT: It's a very promising bot, I made it entirely with some artificial intelligences. I don't have any programming knowledge and I already reached my limit of improvement. All corrections and updates will be welcome."

BOTXI is an advanced, automated cryptocurrency trading bot designed to operate across multiple exchanges simultaneously. It utilizes machine learning algorithms to predict price movements and execute trades based on configurable strategies. The bot features a graphical user interface (GUI) for easy management and monitoring of trading activities.

## Key Features

1. Multi-exchange support
2. Asynchronous operations for improved performance
3. Machine learning-based price prediction
4. Configurable trading parameters per symbol
5. Real-time market data fetching
6. Automatic order management
7. Risk management features (e.g., daily loss limits)
8. Encrypted configuration storage
9. Detailed logging and CSV export of trades
10. GUI for real-time monitoring and control

## Requirements

- Python 3.7+
- ccxt library
- pandas
- scikit-learn
- joblib
- cryptography
- tkinter and ttkbootstrap for GUI

## Installation

1. Clone the repository
2. Install required packages: `pip install ccxt pandas scikit-learn joblib cryptography ttkbootstrap`

## Configuration

The bot uses an encrypted configuration file (`config.enc`) to store sensitive information. To set up:

1. Run the bot for the first time to generate the encryption key
2. Use the GUI to add exchanges and configure trading parameters
3. The configuration will be automatically encrypted and saved

## Usage

1. Run the script: `python BOTXI31fix.py`
2. Use the GUI to start/stop the bot or individual exchange operations
3. Monitor trading activities, open orders, and performance in real-time

## Main Components

### Exchange Initialization and Management

- `initialize_exchanges()`: Sets up connections to configured exchanges
- `reconnect_exchange()`: Handles automatic reconnection to exchanges

### Data Fetching and Processing

- `fetch_ohlcv_async()`: Retrieves OHLCV (Open, High, Low, Close, Volume) data
- `get_market_prices_async()`: Fetches current market prices for configured symbols

### Machine Learning Model

- `train_model()`: Trains a Random Forest Regressor model for price prediction
- `predict_next_price()`: Uses the trained model to predict the next price

### Trading Logic

- `process_symbol()`: Main trading loop for each symbol
- `place_order_async()`: Places buy/sell orders
- `manage_open_buy_orders()`: Manages and updates open buy orders
- `place_sell_orders()`: Places sell orders based on profit targets

### Risk Management

- `calculate_daily_loss()`: Tracks daily losses per symbol
- `deactivate_token_if_needed()`: Stops trading for a symbol if loss threshold is reached

### GUI (Graphical User Interface)

- `BotGUI` class: Manages the entire GUI interface
- Real-time updates for actions, orders, and connection status
- Controls for starting/stopping the bot and individual exchanges

### Data Persistence

- `save_trade_to_csv()`: Records trades in CSV format
- `save_encrypted_config()`: Saves configuration in an encrypted file

## Advanced Features

1. Automatic model retraining based on a configurable interval
2. Rate limiting to prevent API request limits from being exceeded
3. Graceful shutdown procedures to ensure all operations are properly closed
4. Periodic updates of GUI elements for real-time monitoring

## Security Considerations

- API keys and other sensitive data are stored in an encrypted configuration file
- The encryption key is stored separately for added security

## Logging

Detailed logs are saved to `bot.log`, providing insights into the bot's operations, errors, and trading activities.

## Customization

Users can customize various aspects of the bot:

- Trading parameters per symbol (spread, take profit, trade amount, etc.)
- Exchange-specific settings
- Model training parameters
- GUI update intervals

## Limitations and Considerations

- The bot's performance depends on the quality of historical data and market conditions
- Users should thoroughly test the bot with small amounts before deploying with significant capital
- Cryptocurrency markets are highly volatile; use this bot at your own risk

## Future Improvements

- Implementation of additional trading strategies
- Support for more technical indicators
- Enhanced backtesting capabilities
- Integration with additional data sources for improved predictions

## Disclaimer

This bot is for educational and research purposes only. Users are responsible for any financial losses incurred while using this software. Always understand the risks involved in automated trading and cryptocurrency markets.

## Contributing

Contributions to improve BOTXI are welcome. Please submit pull requests or open issues for bugs and feature requests.

## License

[Specify your chosen license here]

---

This README provides a comprehensive overview of the BOTXI trading bot, its features, setup process, and important considerations for users. It's designed to give both technical and non-technical users a clear understanding of the bot's capabilities and how to use it effectively.
