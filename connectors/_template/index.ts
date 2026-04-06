/**
 * Template Connector
 *
 * Copy this file and modify it to create a new Health OS connector.
 * Replace "Template" with your connector name throughout.
 *
 * Every connector must implement the HealthConnector interface.
 */

// TODO: Uncomment when core/schema is implemented
// import type { HealthConnector, HealthEvent, HealthCategory, ConnectorConfig } from '../../core/schema';

// Temporary type definitions until core/schema is built
interface HealthEvent {
  id: string;
  source: string;
  category: string;
  type: string;
  timestamp: Date;
  duration?: number;
  value?: number;
  unit?: string;
  metadata: Record<string, unknown>;
  tags?: string[];
}

interface ConnectorConfig {
  [key: string]: unknown;
}

interface HealthConnector {
  readonly id: string;
  readonly name: string;
  readonly categories: string[];
  readonly description: string;
  init(config: ConnectorConfig): Promise<void>;
  fetchEvents(from: Date, to: Date): Promise<HealthEvent[]>;
  validate(): Promise<{ valid: boolean; errors?: string[] }>;
}

// ============================================================
// YOUR CONNECTOR IMPLEMENTATION STARTS HERE
// ============================================================

export class TemplateConnector implements HealthConnector {
  readonly id = 'template';
  readonly name = 'Template Connector';
  readonly categories = ['custom'];
  readonly description = 'A template connector — replace with your data source description';

  private config: ConnectorConfig = {};

  async init(config: ConnectorConfig): Promise<void> {
    this.config = config;

    // TODO: Initialize your connector
    // - Validate API keys / credentials
    // - Set up HTTP clients
    // - Test connectivity
  }

  async fetchEvents(from: Date, to: Date): Promise<HealthEvent[]> {
    // TODO: Fetch health events from your data source
    // - Call your API or read your data file
    // - Transform the data into HealthEvent format
    // - Return events within the [from, to] date range

    const events: HealthEvent[] = [];

    // Example:
    // const rawData = await this.apiClient.getData(from, to);
    // for (const item of rawData) {
    //   events.push({
    //     id: crypto.randomUUID(),
    //     source: this.id,
    //     category: 'activity',
    //     type: 'steps',
    //     timestamp: new Date(item.date),
    //     value: item.steps,
    //     unit: 'steps',
    //     metadata: { raw: item },
    //   });
    // }

    return events;
  }

  async validate(): Promise<{ valid: boolean; errors?: string[] }> {
    const errors: string[] = [];

    // TODO: Validate that the connector is properly configured
    // - Check required config values exist
    // - Test API connectivity
    // - Verify permissions

    // Example:
    // if (!this.config.apiKey) {
    //   errors.push('API key is required. Set YOUR_CONNECTOR_API_KEY in .env');
    // }

    return {
      valid: errors.length === 0,
      errors: errors.length > 0 ? errors : undefined,
    };
  }
}
