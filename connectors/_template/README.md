# Connector Template

Use this template to build a new Health OS connector.

## How to create a new connector

1. Copy this entire `_template` directory to `connectors/your-connector-name/`
2. Rename files and update the code to match your data source
3. Implement the `HealthConnector` interface
4. Add tests
5. Submit a PR

## File Structure

```
connectors/your-connector/
├── README.md           # Describe your connector (copy and modify this file)
├── index.ts            # Main connector implementation
├── types.ts            # Connector-specific types (optional)
├── .env.example        # Configuration template (API keys, file paths, etc.)
└── __tests__/
    └── index.test.ts   # Tests
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
npm test -- connectors/your-connector
```

Use synthetic data in tests. Never use real health data or real API credentials in test files.
