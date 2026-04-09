# Connector Template

Use this template to build a new OpenHealth connector.

## How to create a new connector

1. Copy this entire `_template` directory to `connectors/your_connector_name/`
2. Rename files and update the code to match your data source
3. Implement the `sync()` entry point following `connector.py`
4. Add tests
5. Submit a PR

## File Structure

```
connectors/your_connector/
├── README.md           # Describe your connector (copy and modify this file)
├── connector.py        # Main connector implementation
├── .env.example        # Configuration template (API keys, file paths, etc.)
└── tests/
    └── test_connector.py   # Tests
```

## Configuration

Each connector uses environment variables for configuration. Define them in `.env.example` with placeholder values:

```
# .env.example
YOUR_CONNECTOR_API_KEY=your-api-key-here
YOUR_CONNECTOR_BASE_URL=https://api.example.com
```

Users copy this to `.env` and fill in their real values. The `.env` file is gitignored.

## Testing

```bash
# Run your connector's tests
python -m unittest discover -s connectors/your_connector/tests
```

Use synthetic data in tests. Never use real health data or real API credentials in test files.
